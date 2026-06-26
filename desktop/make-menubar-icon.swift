#!/usr/bin/env swift
//
// 產生選單列用的 template 圖示 → desktop/menubar-icon.png
// template 圖只看 alpha，畫成黑色，macOS 會依選單列亮/暗自動上色。
// 圖樣：三根上升 K 棒。執行：swift desktop/make-menubar-icon.swift
//
import AppKit
import CoreGraphics

let W = 64, H = 44
let space = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8,
                          bytesPerRow: 0, space: space,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    fatalError("CGContext 建立失敗")
}
ctx.clear(CGRect(x: 0, y: 0, width: W, height: H))
ctx.setFillColor(NSColor.black.cgColor)
ctx.setStrokeColor(NSColor.black.cgColor)
ctx.setLineCap(.round)

// (x中心, 影線下, 影線上, 實體下, 實體上)
let candles: [(CGFloat, CGFloat, CGFloat, CGFloat, CGFloat)] = [
    (14, 5,  27, 9,  20),
    (32, 10, 34, 15, 28),
    (50, 16, 40, 21, 36),
]
let bodyW: CGFloat = 12
for c in candles {
    // 影線
    ctx.setLineWidth(3)
    ctx.move(to: CGPoint(x: c.0, y: c.1)); ctx.addLine(to: CGPoint(x: c.0, y: c.2)); ctx.strokePath()
    // 實體
    let r = CGRect(x: c.0 - bodyW/2, y: c.3, width: bodyW, height: c.4 - c.3)
    ctx.addPath(CGPath(roundedRect: r, cornerWidth: 2.5, cornerHeight: 2.5, transform: nil))
    ctx.fillPath()
}

guard let cg = ctx.makeImage() else { fatalError("makeImage 失敗") }
let rep = NSBitmapImageRep(cgImage: cg)
let data = rep.representation(using: .png, properties: [:])!
try data.write(to: URL(fileURLWithPath: "desktop/menubar-icon.png"))
print("Wrote desktop/menubar-icon.png")
