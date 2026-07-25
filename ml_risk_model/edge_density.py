"""地図タイル画像からの建物・道路密集度の簡易代理指標(交絡確認・診断用)。"""
import os

import numpy as np
from PIL import Image, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def edge_density(image_path):
    """地図タイル画像のエッジ密度(0〜1)を建物・道路密集度の簡易代理指標として返す。"""
    img = Image.open(os.path.join(BASE_DIR, image_path)).convert("L")
    edges = img.filter(ImageFilter.FIND_EDGES)
    arr = np.asarray(edges, dtype=np.float32)
    return float(arr.mean() / 255.0)
