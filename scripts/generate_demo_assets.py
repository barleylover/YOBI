from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "demo-booking.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def korean_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", size=size)
    except OSError:
        return font(size)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1170, 1560), "#F4F0EC")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 70, 1090, 1490), radius=42, fill="white", outline="#DED4CE", width=3)
    draw.rounded_rectangle((80, 70, 1090, 250), radius=42, fill="#F64675")
    draw.rectangle((80, 190, 1090, 250), fill="#F64675")
    draw.text((135, 120), "YOBI STAY", font=font(34, True), fill="white")
    draw.text((135, 174), "Synthetic booking confirmation", font=font(22), fill="#FFE6EE")

    y = 310
    draw.text((135, y), "BOOKING CONFIRMED", font=font(22, True), fill="#7057D9")
    y += 75
    draw.text((135, y), "YOBI Myeongdong Hotel", font=font(44, True), fill="#24151F")
    y += 72
    draw.text((135, y), "21 Demo-ro, Jung-gu, Seoul", font=font(28), fill="#5E5058")
    y += 46
    draw.text((135, y), "서울특별시 중구 데모로 21", font=korean_font(27), fill="#5E5058")
    y += 95

    rows = [
        ("GUEST", "ALEX MORGAN"),
        ("CHECK-IN", "AUG 06, 2026"),
        ("CHECK-OUT", "AUG 09, 2026"),
        ("ROOM", "DELUXE DOUBLE · DEMO"),
        ("BOOKING ID", "YOBI-DEMO-0821"),
    ]
    for label, value in rows:
        draw.text((135, y), label, font=font(18, True), fill="#8B7A83")
        draw.text((430, y - 5), value, font=font(25, True), fill="#24151F")
        y += 75

    draw.rounded_rectangle((130, 1030, 1040, 1245), radius=26, fill="#FFF6E7", outline="#E8C88F", width=2)
    draw.text((175, 1070), "DELIVERY NOTE", font=font(19, True), fill="#9A5A00")
    draw.text((175, 1120), "Food deliveries may be left at the front desk.", font=font(25, True), fill="#4F3824")
    draw.text((175, 1170), "Please show this address to the courier.", font=font(22), fill="#6B5847")

    draw.text((135, 1345), "DEMO ASSET — NOT A REAL RESERVATION", font=font(19, True), fill="#B42318")
    draw.text((135, 1390), "Created for the YOBI hackathon MVP", font=font(20), fill="#7B6D74")
    image.save(OUTPUT, format="PNG", optimize=True)
    print(f"created {OUTPUT}")


if __name__ == "__main__":
    main()
