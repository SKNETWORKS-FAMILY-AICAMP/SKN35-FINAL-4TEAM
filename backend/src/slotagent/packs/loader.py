"""packs/it_ops/v1.0/pack.json (contracts/examples/pack.json 모양) → DB. 잠그기 전 검사: 골든 궤적 4종 채점 결과 = expected"""


def load_pack(conn, pack_dir) -> int:
    raise NotImplementedError


def lock_pack(conn, pack_version_id: int) -> None:
    raise NotImplementedError
