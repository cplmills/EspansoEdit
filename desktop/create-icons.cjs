const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const assetsDir = path.join(__dirname, "assets");
const iconsetDir = path.join(assetsDir, "icon.iconset");

const outputs = [
  ["icon_16x16.png", 16],
  ["icon_16x16@2x.png", 32],
  ["icon_32x32.png", 32],
  ["icon_32x32@2x.png", 64],
  ["icon_128x128.png", 128],
  ["icon_128x128@2x.png", 256],
  ["icon_256x256.png", 256],
  ["icon_256x256@2x.png", 512],
  ["icon_512x512.png", 512],
  ["icon_512x512@2x.png", 1024]
];

fs.mkdirSync(iconsetDir, { recursive: true });

for (const [name, size] of outputs) {
  fs.writeFileSync(path.join(iconsetDir, name), png(size));
}

fs.copyFileSync(path.join(iconsetDir, "icon_512x512@2x.png"), path.join(assetsDir, "icon.png"));
writeIcns(path.join(assetsDir, "icon.icns"));

function png(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const radius = size * 0.22;
  const shadowOffset = Math.max(1, size * 0.018);

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const index = (y * size + x) * 4;
      const coverage = roundedCoverage(x + 0.5, y + 0.5, size, radius);
      if (coverage <= 0) continue;

      const t = y / Math.max(1, size - 1);
      const left = x / Math.max(1, size - 1);
      const base = mix([18, 114, 101], [25, 146, 126], 1 - t * 0.85);
      const accent = mix(base, [40, 72, 98], left * 0.18 + t * 0.12);

      pixels[index] = accent[0];
      pixels[index + 1] = accent[1];
      pixels[index + 2] = accent[2];
      pixels[index + 3] = Math.round(255 * coverage);
    }
  }

  drawRoundedRect(pixels, size, size * 0.2, size * 0.22 + shadowOffset, size * 0.6, size * 0.56, size * 0.055, [15, 55, 68, 80]);
  drawRoundedRect(pixels, size, size * 0.2, size * 0.22, size * 0.6, size * 0.56, size * 0.055, [246, 251, 255, 246]);
  drawRoundedRect(pixels, size, size * 0.27, size * 0.31, size * 0.46, size * 0.08, size * 0.025, [18, 114, 101, 255]);
  drawRoundedRect(pixels, size, size * 0.27, size * 0.46, size * 0.36, size * 0.08, size * 0.025, [18, 114, 101, 255]);
  drawRoundedRect(pixels, size, size * 0.27, size * 0.61, size * 0.42, size * 0.08, size * 0.025, [18, 114, 101, 255]);

  drawCircle(pixels, size, size * 0.76, size * 0.28, size * 0.048, [255, 255, 255, 235]);
  drawCircle(pixels, size, size * 0.76, size * 0.72, size * 0.048, [255, 255, 255, 235]);

  return encodePng(size, size, pixels);
}

function roundedCoverage(x, y, size, radius) {
  const margin = size * 0.055;
  const minX = margin;
  const minY = margin;
  const maxX = size - margin;
  const maxY = size - margin;
  const cx = x < minX + radius ? minX + radius : x > maxX - radius ? maxX - radius : x;
  const cy = y < minY + radius ? minY + radius : y > maxY - radius ? maxY - radius : y;
  const distance = Math.hypot(x - cx, y - cy);
  return clamp(radius + 0.75 - distance, 0, 1);
}

function drawRoundedRect(pixels, size, x, y, width, height, radius, color) {
  const minX = Math.max(0, Math.floor(x - 1));
  const minY = Math.max(0, Math.floor(y - 1));
  const maxX = Math.min(size, Math.ceil(x + width + 1));
  const maxY = Math.min(size, Math.ceil(y + height + 1));
  for (let py = minY; py < maxY; py += 1) {
    for (let px = minX; px < maxX; px += 1) {
      const cx = px + 0.5 < x + radius ? x + radius : px + 0.5 > x + width - radius ? x + width - radius : px + 0.5;
      const cy = py + 0.5 < y + radius ? y + radius : py + 0.5 > y + height - radius ? y + height - radius : py + 0.5;
      const alpha = clamp(radius + 0.75 - Math.hypot(px + 0.5 - cx, py + 0.5 - cy), 0, 1);
      if (alpha > 0) blend(pixels, size, px, py, color, alpha);
    }
  }
}

function drawCircle(pixels, size, cx, cy, radius, color) {
  const minX = Math.max(0, Math.floor(cx - radius - 1));
  const minY = Math.max(0, Math.floor(cy - radius - 1));
  const maxX = Math.min(size, Math.ceil(cx + radius + 1));
  const maxY = Math.min(size, Math.ceil(cy + radius + 1));
  for (let y = minY; y < maxY; y += 1) {
    for (let x = minX; x < maxX; x += 1) {
      const alpha = clamp(radius + 0.75 - Math.hypot(x + 0.5 - cx, y + 0.5 - cy), 0, 1);
      if (alpha > 0) blend(pixels, size, x, y, color, alpha);
    }
  }
}

function blend(pixels, size, x, y, color, coverage) {
  const index = (y * size + x) * 4;
  const sourceAlpha = (color[3] / 255) * coverage;
  const targetAlpha = pixels[index + 3] / 255;
  const outAlpha = sourceAlpha + targetAlpha * (1 - sourceAlpha);
  if (outAlpha <= 0) return;
  for (let i = 0; i < 3; i += 1) {
    pixels[index + i] = Math.round((color[i] * sourceAlpha + pixels[index + i] * targetAlpha * (1 - sourceAlpha)) / outAlpha);
  }
  pixels[index + 3] = Math.round(outAlpha * 255);
}

function encodePng(width, height, rgba) {
  const scanlines = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * (width * 4 + 1);
    scanlines[rowStart] = 0;
    rgba.copy(scanlines, rowStart + 1, y * width * 4, (y + 1) * width * 4);
  }

  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", Buffer.concat([uint32(width), uint32(height), Buffer.from([8, 6, 0, 0, 0])])),
    chunk("IDAT", zlib.deflateSync(scanlines, { level: 9 })),
    chunk("IEND", Buffer.alloc(0))
  ]);
}

function chunk(type, data) {
  const typeBuffer = Buffer.from(type);
  return Buffer.concat([uint32(data.length), typeBuffer, data, uint32(crc32(Buffer.concat([typeBuffer, data])))]);
}

function writeIcns(target) {
  const entries = [
    ["icp4", "icon_16x16.png"],
    ["icp5", "icon_32x32.png"],
    ["icp6", "icon_32x32@2x.png"],
    ["ic07", "icon_128x128.png"],
    ["ic08", "icon_256x256.png"],
    ["ic09", "icon_512x512.png"],
    ["ic10", "icon_512x512@2x.png"],
    ["ic11", "icon_16x16@2x.png"],
    ["ic12", "icon_32x32@2x.png"],
    ["ic13", "icon_128x128@2x.png"],
    ["ic14", "icon_256x256@2x.png"]
  ].map(([type, file]) => {
    const data = fs.readFileSync(path.join(iconsetDir, file));
    return Buffer.concat([Buffer.from(type), uint32(data.length + 8), data]);
  });
  const totalLength = 8 + entries.reduce((sum, entry) => sum + entry.length, 0);
  fs.writeFileSync(target, Buffer.concat([Buffer.from("icns"), uint32(totalLength), ...entries]));
}

function uint32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value >>> 0, 0);
  return buffer;
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let i = 0; i < 8; i += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function mix(a, b, amount) {
  return a.map((value, index) => Math.round(value + (b[index] - value) * amount));
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
