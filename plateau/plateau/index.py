"""建物フットプリントの空間インデックス(STRtreeベース)。"""
import numpy as np
from shapely.geometry import Polygon, Point
from shapely import STRtree

from .parser import Building


class BuildingIndex:
    def __init__(self, buildings: list[Building]):
        self.buildings = buildings
        self.polygons = [Polygon(b.footprint_xy) for b in buildings]
        self.heights = np.array([b.height for b in buildings])
        self.tree = STRtree(self.polygons)

    def __len__(self):
        return len(self.buildings)

    def point_in_building_height(self, x, y):
        """(x, y) がいずれかの建物ポリゴン内にあれば、その建物の高さを返す。
        建物の外なら None。

        注意: shapely 2.xのSTRtree.queryのpredicateは「クエリ側を主語」に
        評価される(query_geometry.within(tree_geometry))。ポリゴン側を主語
        にした「contains」を指定すると常に空集合が返る誤りがあったため、
        「within」に修正済み(実データ検証で発見・修正)。
        """
        pt = Point(x, y)
        idx = self.tree.query(pt, predicate="within")
        if len(idx) == 0:
            return None
        return float(self.heights[idx].max())

    def candidates_for_ray(self, x0, y0, x1, y1):
        """レイの範囲と交差しうる建物ポリゴンの候補(インデックス)を返す。"""
        from shapely.geometry import LineString
        ray = LineString([(x0, y0), (x1, y1)])
        idx = self.tree.query(ray, predicate="intersects")
        return idx, ray
