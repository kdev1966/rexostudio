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
//   enhance  photo amelioree : lumiere et couleurs (Apple), balance des blancs sur
//            les zones blanches, relief ; --enhance applique la meme amelioration
//            avant n'importe quel effet (Vision travaille alors sur la photo amelioree)
//
// Pour style, crop et orient, la sortie est en PNG si son nom finit par .png (la
// transparence d'un detourage est gardee ; orient sans perte), en JPEG sinon.
//
// --persons : ajoute a la reponse JSON les cadres des personnes (corps entier).
// --use-mask <png> : masque des personnes deja calcule (gris, blanc = personne), a la
// place de Vision ; sert au masque affine par MobileSAM (effects_worker/refine.py).
//
// --save-fg <jpg> : enregistre aussi la photo aux couleurs de bord nettoyees
// (« decontaminees »), source du calque des maries dans le PSD a calques.
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
guard ["cutout", "mask", "bw", "blur", "uni", "style", "crop", "orient", "enhance"].contains(effect) else {
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
let rawImage = atOrigin(source)
let extent = rawImage.extent
let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CIContext(options: [.workingColorSpace: srgb])
var report: [String: Any] = [:]       // ajoute a la reponse JSON

// Amelioration avant effet (--enhance, ou effet « enhance ») : trois reglages doux,
// pour ne pas denaturer une photo de mariage.
//  1. lumiere et couleurs : l'amelioration automatique d'Apple (ombres, courbe de
//     tons, vivacite), sans correction des yeux rouges ;
//  2. balance des blancs : les zones tres claires et peu colorees (la robe, une
//     chemise) sont ramenees vers le neutre, a moitie seulement et de 15 % au plus
//     par couleur, pour garder la chaleur des eclairages de soiree ;
//  3. relief : leger contraste local (masque flou a grand rayon).
func enhanced(_ img: CIImage) -> CIImage {
    var r = img
    var applied: [String] = []
    for f in r.autoAdjustmentFilters(options: [.redEye: false]) {
        f.setValue(r, forKey: kCIInputImageKey)
        if let out = f.outputImage { r = out; applied.append(f.name) }
    }
    // Balance des blancs sur une version de 256 px
    let side = 256.0
    let scale = side / Double(max(extent.width, extent.height))
    let w = Int((Double(extent.width) * scale).rounded()), h = Int((Double(extent.height) * scale).rounded())
    var px = [UInt8](repeating: 0, count: w * h * 4)
    let small = r.applyingFilter("CILanczosScaleTransform",
                                 parameters: [kCIInputScaleKey: scale, kCIInputAspectRatioKey: 1.0])
    context.render(atOrigin(small), toBitmap: &px, rowBytes: w * 4,
                   bounds: CGRect(x: 0, y: 0, width: w, height: h), format: .RGBA8, colorSpace: srgb)
    var lum: [Double] = []
    lum.reserveCapacity(w * h)
    for i in 0..<(w * h) {
        lum.append(0.299 * Double(px[i * 4]) + 0.587 * Double(px[i * 4 + 1]) + 0.114 * Double(px[i * 4 + 2]))
    }
    let sorted = lum.sorted()
    let threshold = sorted[Int(Double(sorted.count) * 0.97)]
    var sum = [0.0, 0.0, 0.0], count = 0
    for i in 0..<(w * h) where lum[i] >= threshold {
        let c = [Double(px[i * 4]), Double(px[i * 4 + 1]), Double(px[i * 4 + 2])]
        let hi = c.max()!, lo = c.min()!
        if hi < 250 && hi > 120 && (hi - lo) / hi < 0.25 {      // clair, non brule, peu colore
            for k in 0..<3 { sum[k] += c[k] }
            count += 1
        }
    }
    var gains = [1.0, 1.0, 1.0]
    if count >= max(20, w * h / 500) {
        let mean = (sum[0] + sum[1] + sum[2]) / 3
        gains = (0..<3).map { k in min(1.15, max(0.85, 1 + (mean / sum[k] - 1) * 0.5)) }
        r = r.applyingFilter("CIColorMatrix", parameters: [
            "inputRVector": CIVector(x: CGFloat(gains[0]), y: 0, z: 0, w: 0),
            "inputGVector": CIVector(x: 0, y: CGFloat(gains[1]), z: 0, w: 0),
            "inputBVector": CIVector(x: 0, y: 0, z: CGFloat(gains[2]), w: 0)])
        applied.append("BalanceDesBlancs")
    }
    // Relief
    r = r.applyingFilter("CIUnsharpMask", parameters: [
        kCIInputRadiusKey: Double(max(extent.width, extent.height)) / 150.0,
        kCIInputIntensityKey: 0.25])
    applied.append("Relief")
    report["enhance"] = applied
    report["white_balance"] = gains.map { NSDecimalNumber(string: String(format: "%.3f", $0)) }
    return r.applyingFilter("CIColorClamp").cropped(to: extent)
}

let image = (effect == "enhance" || CommandLine.arguments.contains("--enhance"))
    ? enhanced(rawImage) : rawImage
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
    var info: [String: Any] = [
        "ok": true, "width": Int(extent.width), "height": Int(extent.height),
        "out_width": Int(result.extent.width), "out_height": Int(result.extent.height),
        "coverage": NSDecimalNumber(string: String(format: "%.3f", coverage)),
        "ms": Int(Date().timeIntervalSince(start) * 1000)]
    info.merge(report) { _, new in new }
    print(String(data: try! JSONSerialization.data(withJSONObject: info), encoding: .utf8)!)
    exit(0)
}

// Photo amelioree seule (lumiere, couleurs, balance des blancs, relief)
if effect == "enhance" {
    finish(image, png: pngOutput, coverage: 0)
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

// 1. Masque des personnes (resolution de Vision, en general plus petite que l'image),
//    sauf si --use-mask fournit un masque deja calcule (affine par MobileSAM : voir
//    effects_worker/refine.py) ; --persons ajoute a la reponse le cadre de chaque
//    personne (corps entier), en proportions, origine en haut a gauche.
let usedMask = option("--use-mask")
var buffer: CVPixelBuffer? = nil
if usedMask == nil || CommandLine.arguments.contains("--persons") {
    let request = VNGeneratePersonSegmentationRequest()
    request.qualityLevel = quality
    request.outputPixelFormat = kCVPixelFormatType_OneComponent8
    let humans = VNDetectHumanRectanglesRequest()
    humans.upperBodyOnly = false
    var requests: [VNRequest] = []
    if usedMask == nil { requests.append(request) }
    if CommandLine.arguments.contains("--persons") { requests.append(humans) }
    do {
        // Toujours sur la photo d'origine : sur la photo amelioree (ombres debouchees,
        // relief), Vision voyait moins bien les maries de nuit (photo 5 du studio :
        // couverture 0,053 au lieu de 0,062, la mariee perdue a l'affinage). La photo
        // amelioree a la meme geometrie : le masque lui sert tel quel.
        try VNImageRequestHandler(ciImage: rawImage, options: [:]).perform(requests)
    } catch {
        fail("Vision : \(error.localizedDescription)")
    }
    if usedMask == nil {
        guard let b = request.results?.first?.pixelBuffer else { fail("aucun masque produit") }
        buffer = b
    }
    if CommandLine.arguments.contains("--persons") {
        report["persons"] = (humans.results ?? []).map { o -> [NSDecimalNumber] in
            let b = o.boundingBox
            return [b.minX, 1 - b.maxY, b.width, b.height].map {
                NSDecimalNumber(string: String(format: "%.4f", Double($0))) }
        }
    }
}

// Mise a la taille de l'image (Lanczos : bords plus doux qu'un simple agrandissement)
func fitted(_ small: CIImage) -> CIImage {
    let img = atOrigin(small)
    let sx = extent.width / img.extent.width
    let sy = extent.height / img.extent.height
    return img.applyingFilter("CILanczosScaleTransform",
                              parameters: [kCIInputScaleKey: sy, kCIInputAspectRatioKey: sx / sy])
        .cropped(to: extent)
}

// Bord plus net : le masque de Vision, calcule en basse resolution puis agrandi, a un
// bord flou large. Les valeurs 0,08..0,6 sont etirees sur 0..1 : le bord se resserre
// et ce que Vision voit avec peu de confiance devient plus opaque. Un seuil plus haut
// (0,25..0,75, essaye le 16/11/2026) effacait la main du marie le long du corps,
// detectee a 17 % seulement : rien de ce que Vision voit ne doit disparaitre.
func tightened(_ m: CIImage) -> CIImage {
    let gain = 1.0 / 0.52, bias = -0.08 / 0.52
    return m.applyingFilter("CIColorMatrix", parameters: [
        "inputRVector": CIVector(x: CGFloat(gain), y: 0, z: 0, w: 0),
        "inputGVector": CIVector(x: CGFloat(gain), y: 0, z: 0, w: 0),
        "inputBVector": CIVector(x: CGFloat(gain), y: 0, z: 0, w: 0),
        "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 1),
        "inputBiasVector": CIVector(x: CGFloat(bias), y: CGFloat(bias), z: CGFloat(bias), w: 0)])
        .applyingFilter("CIColorClamp").cropped(to: extent)
}

var mask: CIImage
if let path = usedMask {
    // Masque en niveaux de gris (blanc = personne), aux proportions de l'image
    guard let given = CIImage(contentsOf: URL(fileURLWithPath: path)) else {
        fail("masque illisible : \(path)")
    }
    mask = fitted(given).applyingFilter("CIColorMatrix", parameters: [
        "inputGVector": CIVector(x: 1, y: 0, z: 0, w: 0),
        "inputBVector": CIVector(x: 1, y: 0, z: 0, w: 0),
        "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 0),
        "inputBiasVector": CIVector(x: 0, y: 0, z: 0, w: 1)]).cropped(to: extent)
} else {
    mask = tightened(fitted(CIImage(cvPixelBuffer: buffer!)))
}

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

// Couleurs du bord « decontaminees » : sur le pourtour, un pixel a demi transparent
// melange la personne et le fond d'origine (sombre la nuit). On le remplace par la
// couleur moyenne de la personne autour de lui : flou(image x masque) / flou(masque).
// Au coeur du personnage (masque > 0,9) l'image reste intacte.
let divideKernel = CIColorKernel(source:
    "kernel vec4 rexoDivide(__sample p, __sample m) {" +
    " float a = max(m.r, 0.0001); return vec4(clamp(p.rgb / a, 0.0, 1.0), 1.0); }")!

func decontaminated() -> CIImage {
    let radius = max(4.0, Double(max(extent.width, extent.height)) / 400.0)
    let black = CIImage(color: CIColor(red: 0, green: 0, blue: 0)).cropped(to: extent)
    let premult = image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: black, kCIInputMaskImageKey: mask])
    let blurP = premult.clampedToExtent().applyingFilter("CIGaussianBlur",
        parameters: [kCIInputRadiusKey: radius]).cropped(to: extent)
    let blurM = mask.clampedToExtent().applyingFilter("CIGaussianBlur",
        parameters: [kCIInputRadiusKey: radius]).cropped(to: extent)
    let foreground = divideKernel.apply(extent: extent, arguments: [blurP, blurM])!
    let core = mask.applyingFilter("CIColorMatrix", parameters: [
        "inputRVector": CIVector(x: 10, y: 0, z: 0, w: 0),
        "inputGVector": CIVector(x: 10, y: 0, z: 0, w: 0),
        "inputBVector": CIVector(x: 10, y: 0, z: 0, w: 0),
        "inputBiasVector": CIVector(x: -9, y: -9, z: -9, w: 0)]).applyingFilter("CIColorClamp")
    return image.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: foreground, kCIInputMaskImageKey: core]).cropped(to: extent)
}

if let fgPath = option("--save-fg") {
    // Image opaque aux couleurs de bord nettoyees : calque du PSD (detourage)
    do {
        try context.writeJPEGRepresentation(of: decontaminated(), to: URL(fileURLWithPath: fgPath),
                                            colorSpace: srgb, options: [jpegQuality: 0.95])
    } catch {
        fail("image de premier plan impossible a ecrire : \(error.localizedDescription)")
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
    finish(decontaminated().applyingFilter("CIBlendWithMask", parameters: [
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
