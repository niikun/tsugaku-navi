"""batch_parse_to_parquet.pyで作ったparquet(footprint WKB)から、
BuildingIndexを再構築するラッパー。生GMLの再パースを避けるため。
"""
import pandas as pd
from shapely import wkb as shapely_wkb

from .index import BuildingIndex
from .parser import Building


def load_buildings_from_parquet(parquet_path, mesh_codes=None):
    """parquetから指定メッシュ(Noneなら全件)のBuildingリストを構築する。"""
    df = pd.read_parquet(parquet_path)
    if mesh_codes is not None:
        df = df[df["mesh_code"].astype(str).isin(mesh_codes)]

    buildings = []
    for row in df.itertuples(index=False):
        poly = shapely_wkb.loads(row.footprint_wkb)
        footprint_xy = list(poly.exterior.coords)
        buildings.append(Building(
            footprint_xy=footprint_xy,
            height=row.height,
            base_z=row.base_z,
            height_source=row.height_source,
            gml_id=row.gml_id,
        ))
    return buildings


def build_index_from_parquet(parquet_path, mesh_codes=None):
    buildings = load_buildings_from_parquet(parquet_path, mesh_codes)
    return BuildingIndex(buildings)
