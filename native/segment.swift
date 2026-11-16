// rexo-segment : effets photo par detourage des personnes (Apple Vision, macOS 12+).
//
//   rexo-segment <effet> <entree> <sortie> [--quality accurate|balanced|fast]
//                [--add-mask <png detoure>] [--max <px>]
//
// Effets :
//   cutout   personnes sur fond transparent (PNG)
//   mask     masque en niveaux de gris (PNG, blanc = personne)
//   bw       personnes en couleur, fond en noir et blanc (JPEG)
//   blur     personnes nettes, fond flou (JPEG)
//   orient   copie redressee (orientation EXIF appliquee) et reduite a --max px
//            de grand cote (JPEG) : l'image que voit Vision, a donner a PhotoCraft
//
// --add-mask : la transparence d'un PNG detoure ailleurs (PhotoCraft, Selection
// d'objet dans un cadre) est ajoutee au masque des personnes. Vision trouve les
// tetes et les cheveux ; la Selection d'objet trouve la robe et la traine. Le PNG
// peut etre plus petit que l'image (copie reduite par « orient ») : il est
// agrandi, a condition d'avoir les memes proportions.
//
// Sortie standard : une ligne JSON {"ok":true,"width":..,"height":..,"coverage":..,"ms":..}
// width/height = taille de l'image redressee ; "coverage" = part de l'image occupee
// par le masque (0..1). Code de sortie 0 si l'image est ecrite, 1 sinon
// (message JSON {"ok":false,"error":..}). Tout reste sur la machine.

import CoreImage
import Foundation
import ImageIO
import Vision

func fail(_ message: String) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: ["ok": false, "error": message])
    print(String(data: data, encoding: .utf8)!)
    exit(1)
}

func option(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

func atOrigin(_ image: CIImage) -> CIImage {
    image.transformed(by: CGAffineTransform(translationX: -image.extent.origin.x,
                                            y: -image.extent.origin.y))
}

let args = CommandLine.arguments
guard args.count >= 4 else {
    fail("usage : rexo-segment cutout|mask|bw|blur|orient <entree> <sortie> [options]")
}
let effect = args[1]
let input = URL(fileURLWithPath: args[2])
let output = URL(fileURLWithPath: args[3])
guard ["cutout", "mask", "bw", "blur", "orient"].contains(effect) else {
    fail("effet inconnu : \(effect)")
}
var quality = VNGeneratePersonSegmentationRequest.QualityLevel.accurate
if let q = option("--quality") {
    switch q {
    case "fast": quality = .fast
    case "balanced": quality = .balanced
    case "accurate": quality = .accurate
    default: fail("qualite inconnue : \(q)")
    }
}

let start = Date()
// Orientation EXIF appliquee : on travaille sur l'image telle qu'on la voit.
guard let source = CIImage(contentsOf: input, options: [.applyOrientationProperty: true]) else {
    fail("image illisible : \(input.path)")
}
let image = atOrigin(source)
let extent = image.extent
let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CIContext(options: [.workingColorSpace: srgb])
let jpegQuality = CIImageRepresentationOption(
    rawValue: kCGImageDestinationLossyCompressionQuality as String)

func finish(_ result: CIImage, png: Bool, coverage: Double) -> Never {
    do {
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        if png {
            try context.writePNGRepresentation(of: result, to: output, format: .RGBA8,
                                               colorSpace: srgb)
        } else {
            try context.writeJPEGRepresentation(of: result, to: output, colorSpace: srgb,
                                                options: [jpegQuality: 0.92])
        }
    } catch {
        fail("ecriture impossible : \(error.localizedDescription)")
    }
    let info: [String: Any] = [
        "ok": true, "width": Int(extent.width), "height": Int(extent.height),
        "coverage": NSDecimalNumber(string: String(format: "%.3f", coverage)),
        "ms": Int(Date().timeIntervalSince(start) * 1000)]
    print(String(data: try! JSONSerialization.data(withJSONObject: info), encoding: .utf8)!)
    exit(0)
}

// Copie redressee et reduite (pas de detourage)
if effect == "orient" {
    let limit = Double(option("--max") ?? "") ?? 0
    var result = image
    let side = Double(max(extent.width, extent.height))
    if limit > 0 && side > limit {
        result = image.applyingFilter("CILanczosScaleTransform",
                                      parameters: [kCIInputScaleKey: limit / side,
                                                   kCIInputAspectRatioKey: 1.0])
        result = atOrigin(result)
        result = result.cropped(to: CGRect(x: 0, y: 0, width: floor(result.extent.width),
                                           height: floor(result.extent.height)))
    }
    finish(result, png: false, coverage: 0)
}

// 1. Masque des personnes (resolution de Vision, en general plus petite que l'image)
let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = quality
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
do {
    try VNImageRequestHandler(ciImage: image, options: [:]).perform([request])
} catch {
    fail("Vision : \(error.localizedDescription)")
}
guard let buffer = request.results?.first?.pixelBuffer else { fail("aucun masque produit") }

// Mise a la taille de l'image (Lanczos : bords plus doux qu'un simple agrandissement)
func fitted(_ small: CIImage) -> CIImage {
    let img = atOrigin(small)
    let sx = extent.width / img.extent.width
    let sy = extent.height / img.extent.height
    return img.applyingFilter("CILanczosScaleTransform",
                              parameters: [kCIInputScaleKey: sy, kCIInputAspectRatioKey: sx / sy])
        .cropped(to: extent)
}

var mask = fitted(CIImage(cvPixelBuffer: buffer))

// 2. Masque complementaire (transparence d'un PNG detoure), ajoute au masque
if let extraPath = option("--add-mask") {
    guard let extra = CIImage(contentsOf: URL(fileURLWithPath: extraPath)) else {
        fail("masque complementaire illisible : \(extraPath)")
    }
    let ratio = (extra.extent.width / extra.extent.height) / (extent.width / extent.height)
    guard abs(ratio - 1) < 0.02 else {
        fail("masque complementaire aux proportions differentes de l'image")
    }
    // Alpha recopie dans les composantes de couleur, opaque
    let alpha = fitted(extra).applyingFilter("CIColorMatrix", parameters: [
        "inputRVector": CIVector(x: 0, y: 0, z: 0, w: 1),
        "inputGVector": CIVector(x: 0, y: 0, z: 0, w: 1),
        "inputBVector": CIVector(x: 0, y: 0, z: 0, w: 1),
        "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 0),
        "inputBiasVector": CIVector(x: 0, y: 0, z: 0, w: 1)])
    mask = alpha.applyingFilter("CIMaximumCompositing",
                                parameters: [kCIInputBackgroundImageKey: mask]).cropped(to: extent)
}

// Part de l'image couverte par le masque (moyenne)
let avg = mask.applyingFilter("CIAreaAverage",
                              parameters: [kCIInputExtentKey: CIVector(cgRect: mask.extent)])
var pixel = [UInt8](repeating: 0, count: 4)
context.render(avg, toBitmap: &pixel, rowBytes: 4,
               bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
               format: .RGBA8, colorSpace: nil)
let coverage = Double(pixel[0]) / 255.0

// 3. Effet
switch effect {
case "mask":
    finish(mask, png: true, coverage: coverage)
case "cutout":
    finish(image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: CIImage.empty(), kCIInputMaskImageKey: mask]),
           png: true, coverage: coverage)
case "bw":
    let gray = image.applyingFilter("CIPhotoEffectMono")
    finish(image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: gray, kCIInputMaskImageKey: mask]),
           png: false, coverage: coverage)
default: // blur
    let radius = max(extent.width, extent.height) / 120.0
    let blurred = image.clampedToExtent()
        .applyingFilter("CIGaussianBlur", parameters: [kCIInputRadiusKey: radius])
        .cropped(to: extent)
    finish(image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: blurred, kCIInputMaskImageKey: mask]),
           png: false, coverage: coverage)
}
