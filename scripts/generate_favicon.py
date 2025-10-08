#!/usr/bin/env python3
"""
Generate ICO favicon from SVG logo for notAEC voting system.
Creates multiple sizes for better browser compatibility.
"""

import os
from PIL import Image, ImageDraw
import math

def create_shield_icon(size):
    """Create a shield icon with checkmark at given size."""
    # Create image with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate dimensions
    width, height = size, size
    center_x = width // 2
    center_y = height // 2

    # Shield shape points (centered and properly proportioned)
    shield_points = [
        (center_x, center_y - center_y * 0.8),  # Top point
        (center_x + center_x * 0.7, center_y - center_y * 0.4),  # Top right
        (center_x + center_x * 0.7, center_y + center_y * 0.4),  # Bottom right
        (center_x, center_y + center_y * 0.9),  # Bottom point
        (center_x - center_x * 0.7, center_y + center_y * 0.4),  # Bottom left
        (center_x - center_x * 0.7, center_y - center_y * 0.4),  # Top left
    ]

    # Gradient colors (purple theme)
    colors = [
        (76, 29, 149, 255),   # Dark purple
        (55, 48, 163, 255),   # Medium purple
    ]

    # Create gradient effect by drawing multiple polygons
    steps = 20
    for i in range(steps):
        alpha = i / (steps - 1)
        r = int(colors[0][0] * (1 - alpha) + colors[1][0] * alpha)
        g = int(colors[0][1] * (1 - alpha) + colors[1][1] * alpha)
        b = int(colors[0][2] * (1 - alpha) + colors[1][2] * alpha)

        # Slightly inset the shape for gradient effect
        inset_factor = i * 0.01
        inset_points = []
        for x, y in shield_points:
            dx = x - center_x
            dy = y - center_y
            inset_points.append((
                center_x + dx * (1 - inset_factor),
                center_y + dy * (1 - inset_factor)
            ))

        draw.polygon(inset_points, fill=(r, g, b, 255))

    # Add border
    draw.polygon(shield_points, outline=(30, 41, 59, 255), width=max(1, size // 32))

    # Check mark
    check_start_x = center_x - center_x * 0.4
    check_start_y = center_y - center_y * 0.1
    check_mid_x = center_x - center_x * 0.1
    check_mid_y = center_y + center_y * 0.2
    check_end_x = center_x + center_x * 0.4
    check_end_y = center_y - center_y * 0.3

    check_width = max(1, size // 20)
    draw.line([check_start_x, check_start_y, check_mid_x, check_mid_y, check_end_x, check_end_y],
              fill=(255, 255, 255, 255), width=check_width, joint='curve')

    return img

def main():
    """Generate ICO file with multiple sizes."""
    # Get the project root directory (parent of scripts directory)
    project_root = os.path.dirname(os.path.dirname(__file__))
    static_dir = os.path.join(project_root, 'app', 'static')
    ico_path = os.path.join(static_dir, 'favicon.ico')

    # Generate icons in multiple sizes
    sizes = [16, 24, 32, 48, 64]
    icons = []

    for size in sizes:
        icon = create_shield_icon(size)
        icons.append(icon)

    # Save as ICO with multiple sizes
    icons[0].save(ico_path, format='ICO', sizes=[(icon.size[0], icon.size[1]) for icon in icons])

    print(f"Generated favicon.ico with sizes: {sizes}")
    print(f"Saved to: {ico_path}")

    # Also save individual PNGs for reference
    for size, icon in zip(sizes, icons):
        png_path = os.path.join(static_dir, f'favicon-{size}x{size}.png')
        icon.save(png_path, 'PNG')
        print(f"Saved PNG: {png_path}")

if __name__ == '__main__':
    main()