#!/usr/bin/env swift
//
// 產生 TWStockSim 的 1024×1024 app icon → desktop/icon-1024.png
// 簡約版：深色交易感 squircle + 三根上升 K 棒（紅漲、綠跌）。
// 執行：swift desktop/make-icon.swift   （於專案根目錄）
//
import AppKit
import CoreGraphics

let size: CGFloat = 1024, inset: CGFloat = 96, corner: CGFloat = 228
let space = CGColorSpaceCreateDeviceRGB()

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> NSColor {
    NSColor(red: r, green: g, blue: b, alpha: a)
}
func roundRect(_ r: CGRect, _ rad: CGFloat) -> CGPath {
    CGPath(roundedRect: r, cornerWidth: rad, cornerHeight: rad, transform: nil)
}

let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8,
                    bytesPerRow: 0, space: space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.clear(CGRect(x: 0, y: 0, width: size, height: size))

let sq = CGRect(x: inset, y: inset, width: size - 2*inset, height: size - 2*inset)
let sqPath = roundRect(sq, corner)

// ---- 背景：深色漸層 + 頂部光澤 ----
ctx.saveGState(); ctx.addPath(sqPath); ctx.clip()
let bg = CGGradient(colorsSpace: space,
                    colors: [rgb(0.13,0.18,0.27).cgColor, rgb(0.04,0.06,0.10).cgColor] as CFArray,
                    locations: [0,1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: sq.minX, y: sq.maxY),
                       end: CGPoint(x: sq.maxX, y: sq.minY), options: [])
let sheen = CGGradient(colorsSpace: space,
                       colors: [NSColor.white.withAlphaComponent(0.14).cgColor,
                                NSColor.white.withAlphaComponent(0).cgColor] as CFArray,
                       locations: [0,0.55])!
ctx.drawLinearGradient(sheen, start: CGPoint(x: sq.midX, y: sq.maxY),
                       end: CGPoint(x: sq.midX, y: sq.midY), options: [])
ctx.restoreGState()

// ---- 三根上升 K 棒 ----
let red = rgb(0.92,0.27,0.34), green = rgb(0.16,0.71,0.52)
ctx.saveGState(); ctx.addPath(sqPath); ctx.clip()
let rw = sq.width*0.60, rh = sq.height*0.60
let r = CGRect(x: sq.midX-rw/2, y: sq.midY-rh/2, width: rw, height: rh)
func y(_ f: CGFloat) -> CGFloat { r.minY + f*r.height }
// (影線下, 影線上, 開, 收, 漲?)
let cs: [(CGFloat,CGFloat,CGFloat,CGFloat,Bool)] = [
    (0.02,0.46,0.12,0.36,true),
    (0.22,0.60,0.52,0.30,false),
    (0.46,0.98,0.58,0.90,true),
]
let slot = r.width/3, bw = slot*0.46
for (i,c) in cs.enumerated() {
    let cx = r.minX + slot*(CGFloat(i)+0.5), col = c.4 ? red : green
    ctx.setStrokeColor(col.cgColor); ctx.setLineWidth(16); ctx.setLineCap(.round)
    ctx.move(to: CGPoint(x: cx, y: y(c.0))); ctx.addLine(to: CGPoint(x: cx, y: y(c.1))); ctx.strokePath()
    let top = max(c.2,c.3), bot = min(c.2,c.3)
    ctx.setFillColor(col.cgColor)
    ctx.addPath(roundRect(CGRect(x: cx-bw/2, y: y(bot), width: bw, height: y(top)-y(bot)), 14)); ctx.fillPath()
}
ctx.restoreGState()

let cg = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: cg)
try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "desktop/icon-1024.png"))
print("Wrote desktop/icon-1024.png")
