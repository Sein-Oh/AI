"""테스트용 폴더 트리 생성 도우미."""
import os


def make_tree(base, spec):
    """spec: {"폴더/파일.txt": 크기(바이트) 또는 None(빈 폴더)}. 만든 파일 수를 돌려줍니다."""
    n = 0
    for rel, size in spec.items():
        path = os.path.join(base, *rel.split("/"))
        if size is None:
            os.makedirs(path, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        n += 1
    return n
