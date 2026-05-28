from pathlib import Path


def test_user_flows_doc_exists_and_sections():
    p = Path("docs/USER_FLOWS.md")
    assert p.exists()
    t = p.read_text(encoding="utf-8")
    for s in [
        "Garagem Alvo",
        "## 1. Princípios de UX atuais",
        "## 3. Criar busca monitorada",
        "## 8. Plano e upgrade",
        "## 11. Digest semanal",
        "## 12. Leilões",
        "## 15. Lacunas de UX/produto ainda relevantes",
    ]:
        assert s in t
