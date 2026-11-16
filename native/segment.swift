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
//   uni      personnes sur une couleur unie (--color r,g,b de 0 a 255)
//   style    rendu de couleur sur toute l'image, sans detourage (--name : chaud,
//            froid, vintage-chaud, noir-et-blanc, lumineux, contraste, doux)
//   crop     recadrage au format --ratio L:H (4:5, 9:16, 1:1, 16:9), le plus grand
//            possible, centre sur les personnes trouvees par Vision
//
// Pour style, crop et orient, la sortie est en PNG si son nom finit par .png (la
// transparence d'un detourage est gardee ; orient sans perte), en JPEG sinon.
//
// --save-alpha <png> : enregistre aussi le masque final (personnes + masque
// complementaire) en PNG blanc dont la transparence est le masque : PhotoCraft
// en fait la selection, puis le masque de calque modifiable du PSD.
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
    fail("usage : rexo-segment cutout|mask|bw|blur|uni|style|crop|orient <entree> <sortie> [options]")
}
let effect = args[1]
let input = URL(fileURLWithPath: args[2])
let output = URL(fileURLWithPath: args[3])
guard ["cutout", "mask", "bw", "blur", "uni", "style", "crop", "orient"].contains(effect) else {
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

let pngOutput = output.pathExtension.lowercased() == "png"

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
        "out_width": Int(result.extent.width), "out_height": Int(result.extent.height),
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
    finish(result, png: pngOutput, coverage: 0)
}

// Rendu de couleur sur toute l'image (pas de detourage) ; l'alpha est garde
if effect == "style" {
    let name = option("--name") ?? "chaud"
    var r = image
    func warm(_ img: CIImage, _ kelvin: Double) -> CIImage {
        // Neutre plus froid que la cible = image rechauffee, et inversement
        img.applyingFilter("CITemperatureAndTint", parameters: [
            "inputNeutral": CIVector(x: 6500, y: 0),
            "inputTargetNeutral": CIVector(x: CGFloat(kelvin), y: 0)])
    }
    switch name {
    case "chaud":
        r = warm(r, 7600).applyingFilter("CIColorControls", parameters: [
            kCIInputSaturationKey: 1.06, kCIInputContrastKey: 1.03])
    case "froid":
        r = warm(r, 5400).applyingFilter("CIColorControls", parameters: [
            kCIInputSaturationKey: 0.95])
    case "vintage-chaud":
        r = warm(r, 8000).applyingFilter("CIPhotoEffectTransfer")
            .applyingFilter("CIColorControls", parameters: [
                kCIInputSaturationKey: 0.85, kCIInputContrastKey: 0.92,
                kCIInputBrightnessKey: 0.02])
            .applyingFilter("CIVignette", parameters: [
                kCIInputIntensityKey: 0.7, kCIInputRadiusKey: 1.6])
    case "noir-et-blanc":
        r = r.applyingFilter("CIPhotoEffectMono")
    case "lumineux":
        r = r.applyingFilter("CIHighlightShadowAdjust", parameters: [
            "inputShadowAmount": 0.45, "inputHighlightAmount": 0.95])
            .applyingFilter("CIColorControls", parameters: [kCIInputBrightnessKey: 0.04])
    case "contraste":
        r = r.applyingFilter("CIColorControls", parameters: [
            kCIInputContrastKey: 1.15, kCIInputSaturationKey: 1.08])
    case "doux":
        r = r.applyingFilter("CIColorControls", parameters: [
            kCIInputContrastKey: 0.9, kCIInputSaturationKey: 0.92, kCIInputBrightnessKey: 0.02])
            .applyingFilter("CIBloom", parameters: [
                kCIInputRadiusKey: Double(max(extent.width, extent.height)) / 300.0,
                kCIInputIntensityKey: 0.35])
    default:
        fail("style inconnu : \(name)")
    }
    finish(r.cropped(to: extent), png: pngOutput, coverage: 0)
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

if let alphaPath = option("--save-alpha") {
    let white = CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: extent)
    let alpha = white.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: CIImage.empty(), kCIInputMaskImageKey: mask])
    do {
        try context.writePNGRepresentation(of: alpha, to: URL(fileURLWithPath: alphaPath),
                                           format: .RGBA8, colorSpace: srgb)
    } catch {
        fail("masque impossible a ecrire : \(error.localizedDescription)")
    }
}

// Part de l'image couverte par le masque (moyenne)
let avg = mask.applyingFilter("CIAreaAverage",
                              parameters: [kCIInputExtentKey: CIVector(cgRect: mask.extent)])
var pixel = [UInt8](repeating: 0, count: 4)
context.render(avg, toBitmap: &pixel, rowBytes: 4,
               bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
               format: .RGBA8, colorSpace: nil)
let coverage = Double(pixel[0]) / 255.0

// Cadre des personnes, sur une version reduite du masque (seuil 50 %)
func personBox() -> CGRect? {
    let side = 256.0
    let scale = side / Double(max(extent.width, extent.height))
    let w = Int((Double(extent.width) * scale).rounded()), h = Int((Double(extent.height) * scale).rounded())
    let small = mask.applyingFilter("CILanczosScaleTransform",
                                    parameters: [kCIInputScaleKey: scale, kCIInputAspectRatioKey: 1.0])
    var px = [UInt8](repeating: 0, count: w * h * 4)
    context.render(atOrigin(small), toBitmap: &px, rowBytes: w * 4,
                   bounds: CGRect(x: 0, y: 0, width: w, height: h), format: .RGBA8, colorSpace: nil)
    var x0 = w, y0 = h, x1 = -1, y1 = -1
    for y in 0..<h { for x in 0..<w where px[(y * w + x) * 4] > 127 {
        x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
    } }
    if x1 < 0 { return nil }
    // Lignes du bitmap de haut en bas ; Core Image compte y depuis le bas
    return CGRect(x: Double(x0) / scale, y: Double(h - 1 - y1) / scale,
                  width: Double(x1 - x0 + 1) / scale, height: Double(y1 - y0 + 1) / scale)
}

// 3. Effet
switch effect {
case "uni":
    let parts = (option("--color") ?? "255,255,255").split(separator: ",").compactMap { Double($0) }
    guard parts.count == 3 else { fail("couleur invalide (r,g,b)") }
    let color = CIImage(color: CIColor(red: parts[0] / 255, green: parts[1] / 255, blue: parts[2] / 255))
        .cropped(to: extent)
    finish(image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: color, kCIInputMaskImageKey: mask]),
           png: false, coverage: coverage)
case "crop":
    let parts = (option("--ratio") ?? "4:5").split(separator: ":").compactMap { Double($0) }
    guard parts.count == 2, parts[0] > 0, parts[1] > 0 else { fail("format invalide (L:H)") }
    let ratio = parts[0] / parts[1]
    let W = Double(extent.width), H = Double(extent.height)
    let cw = min(W, H * ratio), ch = cw / ratio
    // Centre : milieu des personnes en largeur ; en hauteur, les visages (haut du cadre)
    // plutot que le milieu du corps ; sans personne, le centre de l'image
    var cx = W / 2, cy = H / 2
    if let box = personBox() {
        cx = Double(box.midX)
        cy = Double(box.maxY) - min(Double(box.height), ch) * 0.45
    }
    let x = min(max(0, cx - cw / 2), W - cw), y = min(max(0, cy - ch / 2), H - ch)
    let rect = CGRect(x: x.rounded(), y: y.rounded(), width: cw.rounded(.down), height: ch.rounded(.down))
    finish(atOrigin(image.cropped(to: rect)), png: pngOutput, coverage: coverage)
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
