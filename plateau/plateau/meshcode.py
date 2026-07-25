"""緯度経度から第3次地域区画(基準地域メッシュ、約1km四方、8桁コード)を求める。

JIS X 0410準拠。PLATEAU CityGMLのファイル名(例: 53394507_bldg_6697_op.gml)の
先頭8桁がこのメッシュコードに対応する。
"""
import math


def latlon_to_mesh3(lat, lon):
    """(lat, lon) から第3次地域区画コード(8桁文字列)を返す。"""
    p = int(lat * 60 / 40)
    a = lat * 60 % 40
    q = int(a / 5)
    b = a % 5
    r = int(b * 60 / 30)

    u = int(lon - 100)
    c = (lon - 100) % 1
    s = int(c * 60 / 7.5)
    d = c * 60 % 7.5
    t = int(d * 60 / 45)

    return f"{p:02d}{u:02d}{q}{s}{r}{t}"


def mesh3_bounds(mesh_code):
    """第3次地域区画コード(8桁)から、そのメッシュの緯度経度範囲(south, west, north, east)を返す。"""
    p = int(mesh_code[0:2])
    u = int(mesh_code[2:4])
    q = int(mesh_code[4])
    s = int(mesh_code[5])
    r = int(mesh_code[6])
    t = int(mesh_code[7])

    lat_south = (p * 40 + q * 5 + r * 30 / 60) / 60
    lat_north = (p * 40 + q * 5 + (r + 1) * 30 / 60) / 60
    lon_west = 100 + u + s * 7.5 / 60 + t * 45 / 3600
    lon_east = 100 + u + s * 7.5 / 60 + (t + 1) * 45 / 3600

    return lat_south, lon_west, lat_north, lon_east


def meshes_for_bbox(south, west, north, east, buffer_deg=0.0):
    """bboxをbuffer_deg分広げた範囲に交差する全ての第3次地域区画コードを返す(set)。"""
    south -= buffer_deg
    west -= buffer_deg
    north += buffer_deg
    east += buffer_deg

    meshes = set()
    # メッシュサイズは緯度方向30秒(=1/120度)、経度方向45秒(=1/80度)
    lat_step = 30 / 3600
    lon_step = 45 / 3600

    lat = south
    while lat <= north:
        lon = west
        while lon <= east:
            meshes.add(latlon_to_mesh3(lat, lon))
            lon += lon_step
        lon = east
        meshes.add(latlon_to_mesh3(lat, lon))
        lat += lat_step
    lat = north
    lon = west
    while lon <= east:
        meshes.add(latlon_to_mesh3(lat, lon))
        lon += lon_step
    meshes.add(latlon_to_mesh3(north, east))

    return meshes


if __name__ == "__main__":
    # サンプルメッシュ(53394507)の範囲を検証
    bounds = mesh3_bounds("53394507")
    print("53394507の範囲(south, west, north, east):", bounds)
    center_lat = (bounds[0] + bounds[2]) / 2
    center_lon = (bounds[1] + bounds[3]) / 2
    recomputed = latlon_to_mesh3(center_lat, center_lon)
    print(f"中心({center_lat:.6f}, {center_lon:.6f}) から逆算したメッシュコード: {recomputed}")
    assert recomputed == "53394507", "メッシュコード変換の往復チェックに失敗"
    print("往復チェックOK")
