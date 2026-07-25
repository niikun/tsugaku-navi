"""v3(件数/率回帰)用のセル列挙。

v1/v2の`enumerate_train_cells`/`enumerate_block_cells`は正例/負例に分類して
返していたが、v3では選抜(層化サンプリング・負例マッチング)自体を廃止し、
「ブロック内・都境界から500m以上内側」という条件を満たす全セルをそのまま返す。
事故件数0のセルも本物のデータ点として扱う。
"""
from tokyo_boundary import is_deep_inside_tokyo


def enumerate_all_cells(blocks, lat_step, lon_step, block_lat_step, block_lon_step,
                          val_blocks=None, buffer_m=None):
    """blocks内の全セルを列挙する。

    val_blocksとbuffer_mが両方指定された場合(train側の呼び出し)、val_blockに
    隣接するセルのうちbuffer_m未満の距離にあるものを除外する。eval側は
    val_blocks=Noneで呼び出す(バッファ除外はtrain側だけの制約)。
    """
    import math
    buffer_lat_deg = buffer_m / 111000.0 if buffer_m else 0.0
    buffer_lon_deg = (buffer_m / (111000.0 * math.cos(math.radians(35.7)))) if buffer_m else 0.0

    cells = []
    for bgx, bgy in blocks:
        lat_min, lat_max = bgy * block_lat_step, (bgy + 1) * block_lat_step
        lon_min, lon_max = bgx * block_lon_step, (bgx + 1) * block_lon_step
        gy_min, gy_max = int(lat_min // lat_step), int(lat_max // lat_step)
        gx_min, gx_max = int(lon_min // lon_step), int(lon_max // lon_step)
        for gy in range(gy_min, gy_max + 1):
            for gx in range(gx_min, gx_max + 1):
                lat_center = (gy + 0.5) * lat_step
                lon_center = (gx + 0.5) * lon_step
                cell_bgx = int(lon_center // block_lon_step)
                cell_bgy = int(lat_center // block_lat_step)
                if (cell_bgx, cell_bgy) != (bgx, bgy):
                    continue

                if val_blocks is not None and buffer_m:
                    excluded = False
                    for dbgx, dbgy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                        neighbor = (bgx + dbgx, bgy + dbgy)
                        if neighbor not in val_blocks:
                            continue
                        if dbgy == 1 and (bgy + 1) * block_lat_step - lat_center < buffer_lat_deg:
                            excluded = True
                        elif dbgy == -1 and lat_center - bgy * block_lat_step < buffer_lat_deg:
                            excluded = True
                        elif dbgx == 1 and (bgx + 1) * block_lon_step - lon_center < buffer_lon_deg:
                            excluded = True
                        elif dbgx == -1 and lon_center - bgx * block_lon_step < buffer_lon_deg:
                            excluded = True
                    if excluded:
                        continue

                if not is_deep_inside_tokyo(lat_center, lon_center):
                    continue

                cells.append((gx, gy))
    return sorted(set(cells))
