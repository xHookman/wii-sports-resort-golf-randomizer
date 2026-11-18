import sys, math
sys.path.insert(0, '/home/user/wsr/tools')
from PIL import Image, ImageDraw, ImageFont
from render3d import mesh, render
COL = {'shore': (120, 110, 100), 'seabed': (30, 80, 150), 'bed': (60, 120, 200), 'water': (60, 120, 200), 'bank': (120, 110, 100), 'ob': (46, 110, 52), 'rough': (86, 160, 70), 'fairway': (140, 205, 95), 'green': (175, 235, 120),
       'collar': (150, 220, 105), 'bunker': (232, 214, 150)}
def topview(g, pmp_objs=None, W=420, title=''):
    V = g['V']
    xs = V[:, 0]; zs = V[:, 2]
    X0, X1, Z0, Z1 = xs.min() - 100, xs.max() + 100, zs.min() - 100, zs.max() + 100
    S = W / (X1 - X0); H = int((Z1 - Z0) * S)
    im = Image.new('RGB', (W, H + 34), (25, 55, 95)); dr = ImageDraw.Draw(im)
    for f, lab in g['tris']:
        dr.polygon([((V[i][0] - X0) * S, 34 + (V[i][2] - Z0) * S) for i in f], fill=COL[lab])
    if pmp_objs:
        for o in pmp_objs:
            px = (o['pos'][0] - X0) * S; pz = 34 + (o['pos'][2] - Z0) * S; t = (o['grp'], o['typ'])
            if t in [(2, 2), (2, 3)]: dr.ellipse([px - 3, pz - 3, px + 3, pz + 3], fill=(20, 70, 25), outline=(10, 30, 10))
            elif t == (2, 0): dr.rectangle([px - 5, pz - 5, px + 5, pz + 5], fill=(255, 255, 255), outline=(0, 0, 0))
            elif t == (2, 1): dr.ellipse([px - 3, pz - 3, px + 3, pz + 3], fill=(255, 240, 0))
            elif t == (11, 1): dr.ellipse([px - 6, pz - 6, px + 6, pz + 6], outline=(230, 30, 30), width=3)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 17)
    dr.rectangle([0, 0, W, 32], fill=(15, 25, 40)); dr.text((8, 7), title, font=font, fill=(235, 240, 250))
    return im
