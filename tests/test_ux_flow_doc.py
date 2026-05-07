from pathlib import Path

def test_ux_flow_doc_exists_and_sections():
    p = Path('docs/UX_FLOW.md')
    assert p.exists()
    t = p.read_text(encoding='utf-8')
    for s in [
        '## 1. Visão geral do produto','## 3. Mapa macro de navegação','## 12. /plan','## 13. /upgrade','## 20. Lacunas conhecidas'
    ]:
        assert s in t
