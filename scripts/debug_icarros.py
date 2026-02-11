"""
Debug Script - Descobrir Seletores Reais do iCarros

Este script baixa o HTML real do iCarros e mostra a estrutura
para você descobrir os seletores corretos.

Uso:
    python scripts/debug_icarros.py
"""

import requests
from bs4 import BeautifulSoup
import json


def debug_icarros():
    """Baixa HTML do iCarros e analisa estrutura."""
    
    print("🔍 Debugando iCarros...\n")
    
    # URL de teste
    url = "https://www.icarros.com.br/carros/saopaulo?q=civic&ordenacao=relevancia"
    
    print(f"📡 Baixando: {url}\n")
    
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        print(f"Status: {resp.status_code}")
        print(f"Content-Length: {len(resp.text):,} bytes\n")
        
        if resp.status_code != 200:
            print(f"❌ Erro: Status {resp.status_code}")
            return
        
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Salva HTML para inspeção
        with open("debug_icarros.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("💾 HTML salvo em: debug_icarros.html\n")
        
        # ========== ANÁLISE ESTRUTURAL ==========
        print("="*60)
        print("📊 ANÁLISE DA ESTRUTURA HTML")
        print("="*60 + "\n")
        
        # Tags principais
        print("🏷️  Tags principais:")
        print(f"  - <article>: {len(soup.select('article'))}")
        print(f"  - <li>: {len(soup.select('li'))}")
        print(f"  - <div>: {len(soup.select('div'))}")
        print(f"  - <a>: {len(soup.select('a'))}")
        print(f"  - <img>: {len(soup.select('img'))}\n")
        
        # Links com "anuncio"
        anuncio_links = soup.select("a[href*='anuncio']")
        print(f"🔗 Links com 'anuncio': {len(anuncio_links)}")
        
        if anuncio_links:
            print("\n   Primeiros 3 links:")
            for i, link in enumerate(anuncio_links[:3], 1):
                href = link.get("href", "")
                text = link.get_text(strip=True)[:50]
                print(f"   {i}. {href}")
                print(f"      Texto: {text}...")
        
        print()
        
        # Classes comuns
        print("🎨 Classes mais comuns (que podem ser cards):")
        class_counts = {}
        for el in soup.select("[class]"):
            classes = el.get("class", [])
            if isinstance(classes, list):
                for cls in classes:
                    if any(keyword in cls.lower() for keyword in ['card', 'item', 'anuncio', 'lista', 'result', 'vehicle', 'veiculo']):
                        class_counts[cls] = class_counts.get(cls, 0) + 1
        
        for cls, count in sorted(class_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"   .{cls}: {count}")
        
        print()
        
        # IDs relevantes
        print("🆔 IDs relevantes:")
        ids = [el.get("id") for el in soup.select("[id]") if el.get("id")]
        relevant_ids = [id for id in ids if any(k in id.lower() for k in ['result', 'lista', 'anuncio', 'card'])]
        for id in relevant_ids[:10]:
            print(f"   #{id}")
        
        print()
        
        # ========== ANÁLISE DE CARDS POTENCIAIS ==========
        print("="*60)
        print("🔍 TENTANDO SELETORES CONHECIDOS")
        print("="*60 + "\n")
        
        selectors = [
            ("ul.listaAnuncios li", "Lista clássica iCarros"),
            ("ul.listaAnuncios > li", "Lista clássica iCarros (direto)"),
            ("li.even, li.odd", "Li com classes even/odd"),
            ("article", "Article tags"),
            (".item-lista", "Classe .item-lista"),
            ("div[class*='card']", "Divs com 'card' na classe"),
            ("div[class*='anuncio']", "Divs com 'anuncio' na classe"),
            ("li:has(a[href*='anuncio'])", "Li com link de anúncio"),
            ("div:has(a[href*='anuncio'])", "Div com link de anúncio"),
        ]
        
        for selector, desc in selectors:
            try:
                elements = soup.select(selector)
                if elements:
                    print(f"✅ {selector}")
                    print(f"   {desc}")
                    print(f"   Encontrados: {len(elements)} elementos\n")
                    
                    # Mostra estrutura do primeiro
                    if len(elements) > 0:
                        first = elements[0]
                        print(f"   Estrutura do primeiro:")
                        print(f"   Tag: {first.name}")
                        print(f"   Classes: {first.get('class', [])}")
                        print(f"   ID: {first.get('id', 'N/A')}")
                        
                        # Procura link
                        link = first.select_one("a[href]")
                        if link:
                            print(f"   Link: {link.get('href', '')[:60]}...")
                        
                        # Procura título
                        title_candidates = first.select("h1, h2, h3, h4, strong")
                        if title_candidates:
                            print(f"   Título: {title_candidates[0].get_text(strip=True)[:50]}...")
                        
                        print()
                        
            except Exception as e:
                print(f"❌ {selector}: Erro - {e}\n")
        
        # ========== INSPEÇÃO MANUAL ==========
        print("="*60)
        print("👁️  PRÓXIMOS PASSOS - INSPEÇÃO MANUAL")
        print("="*60 + "\n")
        
        print("1. Abra o arquivo: debug_icarros.html no navegador")
        print("2. Pressione F12 (DevTools)")
        print("3. Clique no ícone de seleção (canto superior esquerdo)")
        print("4. Clique em um card de anúncio")
        print("5. Veja no DevTools:")
        print("   - Tag do elemento (ex: <li>, <article>, <div>)")
        print("   - Classes (ex: class='item-lista even')")
        print("   - Estrutura interna (onde está título, preço, etc)")
        print("\n6. Anote os seletores e atualize o scraper!\n")
        
        # ========== EXPORT PARA ANÁLISE ==========
        print("="*60)
        print("💾 EXPORTANDO DADOS PARA ANÁLISE")
        print("="*60 + "\n")
        
        # Exporta primeiros 5 elementos de cada seletor que funcionou
        analysis = {}
        
        for selector, desc in selectors:
            try:
                elements = soup.select(selector)
                if elements:
                    analysis[selector] = {
                        "description": desc,
                        "count": len(elements),
                        "samples": []
                    }
                    
                    for el in elements[:5]:
                        sample = {
                            "tag": el.name,
                            "classes": el.get("class", []),
                            "id": el.get("id"),
                            "has_link": bool(el.select_one("a[href]")),
                            "link_href": el.select_one("a[href]").get("href") if el.select_one("a[href]") else None,
                            "text_preview": el.get_text(strip=True)[:100]
                        }
                        analysis[selector]["samples"].append(sample)
            except:
                pass
        
        with open("debug_icarros_analysis.json", "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        
        print("💾 Análise salva em: debug_icarros_analysis.json")
        print("\n✅ Debug completo!\n")
        
    except Exception as e:
        print(f"❌ Erro: {e}")


if __name__ == "__main__":
    debug_icarros()
