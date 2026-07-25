"""
PLATEAU CityGML(建築物、LOD1)から、建物のフットプリント(2Dポリゴン)・
高さ・ベース標高を抽出するパーサー。

対応データ: G空間情報センター配布のPLATEAU CityGML v2(building/2.0名前空間)。
座標系は EPSG:6697 (JGD2011 経緯度+標高の複合参照系、水平成分は EPSG:6668)。
このモジュールは緯度経度のまま読み込み、pointcloudモジュールと同じ
EPSG:6677(平面直角座標系第9系)へ変換して扱う。
"""
from dataclasses import dataclass
import numpy as np
from lxml import etree
from shapely.geometry import Polygon
from pyproj import Transformer

BLDG_NS = "{http://www.opengis.net/citygml/building/2.0}"
GML_NS = "{http://www.opengis.net/gml}"

# CityGMLのmeasuredHeightで「欠損」を表すセンチネル値(実データで確認済み)
HEIGHT_SENTINEL = -9999.0


@dataclass
class Building:
    footprint_xy: np.ndarray  # (N, 2) EPSG:6677座標系での外周リング [x, y]
    height: float             # 建物高さ(m)。measuredHeight優先、欠損時はジオメトリ由来
    base_z: float             # 建物底面の標高(m、参考値)
    height_source: str        # "measured" または "geometry"
    gml_id: str


def _parse_pos_list(text):
    vals = [float(v) for v in text.split()]
    return np.array(vals).reshape(-1, 3)  # (lat, lon, z)


def _extract_floor_face(solid_elem):
    """lod1Solid内の各面のうち、最も低い平均Zを持つ面を床面(フットプリント)とみなす。
    戻り値: (lat, lon)の外周リング配列, (base_z, top_z)
    """
    faces = []
    for member in solid_elem.findall(f"{GML_NS}surfaceMember"):
        poslist = member.find(f".//{GML_NS}posList")
        if poslist is None or not poslist.text:
            continue
        faces.append(_parse_pos_list(poslist.text))
    if not faces:
        return None, None
    mean_zs = [f[:, 2].mean() for f in faces]
    floor = faces[int(np.argmin(mean_zs))]
    base_z = float(floor[:, 2].mean())
    top_z = max(f[:, 2].max() for f in faces)
    return floor[:, :2], (base_z, top_z)  # (lat, lon)


def load_citygml_buildings(paths, target_crs="EPSG:6677",
                            source_crs="EPSG:6668"):
    """
    1つ以上のCityGML(建築物)ファイルを読み込み、Buildingのリストを返す。

    Parameters
    ----------
    paths : str または list[str]
    target_crs : 出力する平面座標系(既定: pointcloudモジュールと同じ第9系)
    source_crs : CityGMLの水平座標系(既定: JGD2011経緯度)

    Returns
    -------
    list[Building]
    """
    if isinstance(paths, str):
        paths = [paths]

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    buildings = []

    for path in paths:
        context = etree.iterparse(path, events=("end",), tag=f"{BLDG_NS}Building")
        for event, elem in context:
            gml_id = elem.get(f"{GML_NS}id", "")
            h_elem = elem.find(f"{BLDG_NS}measuredHeight")
            measured_h = None
            if h_elem is not None and h_elem.text:
                v = float(h_elem.text)
                if v != HEIGHT_SENTINEL:
                    measured_h = v

            solid = elem.find(
                f"{BLDG_NS}lod1Solid/{GML_NS}Solid/{GML_NS}exterior/{GML_NS}CompositeSurface")
            if solid is None:
                elem.clear()
                continue

            ring_latlon, zrange = _extract_floor_face(solid)
            if ring_latlon is None or len(ring_latlon) < 4:
                elem.clear()
                continue

            base_z, top_z = zrange
            geom_h = top_z - base_z

            if measured_h is not None:
                height, source = measured_h, "measured"
            else:
                height, source = geom_h, "geometry"

            # 緯度経度 → 平面座標系(m)。ring_latlonは(lat, lon)なので
            # always_xy=Trueのtransformerには(lon, lat)の順で渡す
            lon = ring_latlon[:, 1]
            lat = ring_latlon[:, 0]
            x, y = transformer.transform(lon, lat)
            footprint_xy = np.column_stack([x, y])

            try:
                poly = Polygon(footprint_xy)
                if not poly.is_valid or poly.area <= 0:
                    elem.clear()
                    continue
            except Exception:
                elem.clear()
                continue

            buildings.append(Building(
                footprint_xy=footprint_xy,
                height=height,
                base_z=base_z,
                height_source=source,
                gml_id=gml_id,
            ))

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

    return buildings
