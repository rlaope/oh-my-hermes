// MIT; Copyright (c) 2026 Minho Hwang (revfactory).
// From revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 scripts/tools/cutout.swift; comments translated.
// macOS-only and opt-in: prep_images.py --cutout compiles it with swiftc into the project. Full notice: ../../LICENSE.upstream.
// Usage: cutout <input image> <output PNG> [instance indexes]
// Makes the background transparent with the Apple Vision foreground instance mask (subject pixels unchanged).
import Foundation
import Vision
import CoreImage
import AppKit

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: cutout in out.png"); exit(1) }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
guard let ciImage = CIImage(contentsOf: inURL, options: [.applyOrientationProperty: true]) else { print("load fail"); exit(1) }

let handler = VNImageRequestHandler(ciImage: ciImage, options: [:])
let req = VNGenerateForegroundInstanceMaskRequest()
do { try handler.perform([req]) } catch { print("vision fail: \(error)"); exit(1) }
guard let result = req.results?.first else { print("no foreground"); exit(2) }
// Instance choice: only the listed indexes when given, otherwise all
var instances = result.allInstances
if args.count >= 4 {
  let pick = IndexSet(args[3].split(separator: ",").compactMap { Int($0) })
  instances = pick
}
print("instances: \(Array(result.allInstances))")
do {
  let buf = try result.generateMaskedImage(ofInstances: instances, from: handler, croppedToInstancesExtent: false)
  let out = CIImage(cvPixelBuffer: buf)
  let ctx = CIContext()
  try ctx.writePNGRepresentation(of: out, to: outURL, format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
  print("ok \(outURL.path)")
} catch { print("mask fail: \(error)"); exit(1) }
