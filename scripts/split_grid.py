"""Split a transparent 3x3 PNG/GIF at empty gutters, preserving full frames.

Requires Pillow. No background removal, resizing, or added outlines.
"""
import argparse
import json
import os
from pathlib import Path
from PIL import Image, ImageChops


def find_cuts(alpha, axis):
    width, height = alpha.size
    length = width if axis == 'x' else height
    empty = []
    for pos in range(length):
        strip = (pos, 0, pos+1, height) if axis == 'x' else (0, pos, width, pos+1)
        empty.append(alpha.crop(strip).getbbox() is None)
    cuts = [0]
    for fraction in (1/3, 2/3):
        target = length*fraction
        candidates = [p for p in range(max(1, int(target-length*.10)),
                                      min(length-1, int(target+length*.10))+1) if empty[p]]
        if not candidates:
            raise ValueError(f'No transparent {axis} gutter near {fraction:.2f}; inspect or repair source, do not crop through a character.')
        cuts.append(min(candidates, key=lambda p: abs(p-target)))
    return cuts + [length]


def split(source, output):
    with Image.open(source) as image:
        animated = image.format == 'GIF' and getattr(image, 'n_frames', 1) > 1
        loop = image.info.get('loop')
        frames, durations = [], []
        for n in range(getattr(image, 'n_frames', 1)):
            image.seek(n)
            frames.append(image.convert('RGBA').copy())
            durations.append(image.info.get('duration', 100))
    union = frames[0].getchannel('A')
    for frame in frames[1:]:
        union = ImageChops.lighter(union, frame.getchannel('A'))
    if union.getextrema()[0] == 255:
        raise ValueError('Source has no transparent pixels; remove the background first.')
    xs, ys = find_cuts(union, 'x'), find_cuts(union, 'y')
    # Border content may already be truncated in the source; do not claim it is complete.
    w, h = union.size
    if any(union.crop(box).getbbox() for box in [(0,0,w,1),(0,h-1,w,h),(0,0,1,h),(w-1,0,w,h)]):
        raise ValueError('Content touches the sheet edge; inspect/repair its completeness before splitting.')
    boxes = [(xs[c],ys[r],xs[c+1],ys[r+1]) for r in range(3) for c in range(3)]
    for box in boxes:
        if union.crop(box).getbbox() is None:
            raise ValueError('An expected sticker cell is empty.')
    output.mkdir(parents=True, exist_ok=True)
    config_dir = output.parent / 'config'
    manifest_path = config_dir / f'{output.name}-manifest.json'
    targets = [output/f'{n:02d}.{ "gif" if animated else "png"}' for n in range(1,10)]
    if any(p.exists() for p in targets) or manifest_path.exists():
        raise FileExistsError('Output already exists; choose a new output directory.')
    for box, target in zip(boxes, targets):
        # Use one fixed cell box for all frames. Never recenter or trim each frame.
        crops = [frame.crop(box) for frame in frames]
        if animated:
            encoded = []
            for crop in crops:
                pal = crop.convert('RGB').quantize(colors=255, method=Image.Quantize.MEDIANCUT)
                pal.paste(255, mask=crop.getchannel('A').point(lambda x: 255 if x < 128 else 0))
                encoded.append(pal)
            options = dict(save_all=True, append_images=encoded[1:], duration=durations,
                           disposal=2, transparency=255, optimize=False)
            if loop is not None:
                options['loop'] = loop
            encoded[0].save(target, **options)
        else:
            crops[0].save(target)
        with Image.open(target) as result:
            assert result.size == crops[0].size
            actual_duration = 0
            for n in range(getattr(result,'n_frames',1)):
                result.seek(n)
                actual_duration += result.info.get('duration', 0)
                assert result.convert('RGBA').getchannel('A').getextrema()[0] == 0
            if animated:
                assert actual_duration == sum(durations)
                assert result.info.get('loop') == loop
    manifest = dict(source=str(source.resolve()), animated=animated, boxes=boxes,
                    duration_ms=sum(durations) if animated else None,
                    files=[Path(os.path.relpath(p, config_dir)).as_posix() for p in targets])
    config_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Saved nine independent {"GIFs" if animated else "PNGs"}: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    split(args.source, args.output)
