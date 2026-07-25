"""
PLATEAU建物ポリゴン(BuildingIndex)に対する視界解析。

pointcloudモジュールのSightlineAnalyzerと同じ特徴量セットを、
ラスタ(nDSM)ではなくベクタ(建物ポリゴン+高さ)に対するレイ-ポリゴン交差判定
で計算する。ラスタ化を経ないため、地面点補間に起因するアーチファクト
(pointcloudモジュールで発見・修正した問題)がそもそも発生しない。

制約: PLATEAU LOD1は建物のみを捉え、塀・植栽・仮設物は含まない
(松山市PLATEAU実証でも同じ制約が報告されている)。
"""
import numpy as np

from .index import BuildingIndex


class PlateauSightlineAnalyzer:
    def __init__(self, index: BuildingIndex):
        self.index = index

    def query_point_height(self, x, y):
        """クエリ地点が建物内にあれば、その建物の高さを返す。建物外ならNone。"""
        return self.index.point_in_building_height(x, y)

    def sightline_distance(self, x, y, angle_rad, max_radius=50.0,
                            eye_height=1.5):
        """
        (x, y) から angle_rad 方向に、高さ eye_height を超える建物に
        ぶつかるまでの距離を返す。ぶつからなければ max_radius。
        """
        dx, dy = np.cos(angle_rad), np.sin(angle_rad)
        x1, y1 = x + dx * max_radius, y + dy * max_radius

        idx, ray = self.index.candidates_for_ray(x, y, x1, y1)
        best = max_radius
        for i in idx:
            h = self.index.heights[i]
            if h <= eye_height:
                continue
            poly = self.index.polygons[i]
            if not ray.intersects(poly):
                continue
            inter = ray.intersection(poly)
            if inter.is_empty:
                continue
            coords = _extract_coords(inter)
            for cx, cy in coords:
                d = float(np.hypot(cx - x, cy - y))
                if d < best:
                    best = d
        return best

    def compute_features(self, x, y, n_rays=36, max_radius=50.0,
                          eye_height=1.5, open_threshold=20.0):
        """
        pointcloud.SightlineAnalyzer.compute_features と同じ特徴量セットを返す。
        """
        angles = np.linspace(0, 2 * np.pi, n_rays, endpoint=False)
        dists = np.array([
            self.sightline_distance(x, y, a, max_radius, eye_height)
            for a in angles
        ])
        return {
            "mean_sightline_dist": float(dists.mean()),
            "min_sightline_dist": float(dists.min()),
            "std_sightline_dist": float(dists.std()),
            "open_fraction": float((dists > open_threshold).mean()),
            "_raw_distances": dists,
        }


def _extract_coords(geom):
    """shapelyのIntersection結果(Point/LineString/Multi*/GeometryCollection)
    から座標点のリストを取り出す。"""
    gt = geom.geom_type
    if gt == "Point":
        return [(geom.x, geom.y)]
    if gt == "MultiPoint":
        return [(p.x, p.y) for p in geom.geoms]
    if gt == "LineString":
        return list(geom.coords)
    if gt in ("MultiLineString", "GeometryCollection"):
        coords = []
        for g in geom.geoms:
            coords.extend(_extract_coords(g))
        return coords
    return []
