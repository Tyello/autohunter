"""
Debug Script - Descobrir Seletores do Mercado Livre

Testa a URL sugerida: lista.mercadolivre.com.br/Honda-Civic

Uso:
    python scripts/debug_mercadolivre.py
"""

import requests
from bs4 import BeautifulSoup
import json


def debug_mercadolivre():
    """Baixa HTML do ML e analisa estrutura."""
    
    print("🔍 Debugando Mercado Livre...\n")
    
    # URL correta (sugerida pelo usuário)
    url = "https://lista.mercadolivre.com.br/Honda-Civic"
    
    print(f"📡 Baixando: {url}\n")
    
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        })
        
        print(f"Status: {resp.status_code}")
        print(f"Content-Length: {len(resp.text):,} bytes\n")
        
        if resp.status_code != 200:
            print(f"❌ Erro: Status {resp.status_code}")
            if resp.status_code == 403:
                print("   Possível bloqueio. Tente:")
                print("   - Adicionar mais headers")
                print("   - Usar proxy")
                print("   - Force browser mode")
            return
        
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Salva HTML
        with open("debug_mercadolivre.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("💾 HTML salvo em: debug_mercadolivre.html\n")
        
        # ========== ANÁLISE ==========
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
        
        # Links com MLB (anúncios)
        mlb_links = soup.select("a[href*='MLB']")
        print(f"🔗 Links com 'MLB' (anúncios): {len(mlb_links)}")
        
        if mlb_links:
            print("\n   Primeiros 5 links:")
            for i, link in enumerate(mlb_links[:5], 1):
                href = link.get("href", "")
                text = link.get_text(strip=True)[:50]
                print(f"   {i}. {href[:80]}...")
                if text:
                    print(f"      Texto: {text}")
        
        print()
        
        # Classes conhecidas do ML
        print("🎨 Seletores conhecidos do ML:")
        ml_selectors = [
            ("li.ui-search-layout__item", "Item de busca"),
            ("div.ui-search-result", "Resultado de busca"),
            ("div.ui-search-result__wrapper", "Wrapper do resultado"),
            ("div.ui-search-result__content", "Conteúdo do resultado"),
            (".ui-search-item__title", "Título"),
            (".price-tag-fraction", "Preço"),
            (".ui-search-item__location", "Localização"),
        ]
        
        for selector, desc in ml_selectors:
            elements = soup.select(selector)
            if elements:
                print(f"✅ {selector:40s} {len(elements):3d} elementos - {desc}")
                
                # Mostra primeiro elemento se for um card
                if "item" in selector or "result" in selector:
                    first = elements[0]
                    
                    # Procura título
                    title = first.select_one("h2, .ui-search-item__title")
                    if title:
                        print(f"   Título: {title.get_text(strip=True)[:60]}...")
                    
                    # Procura preço
                    price = first.select_one(".price-tag-fraction, span[class*='price']")
                    if price:
                        print(f"   Preço: {price.get_text(strip=True)}")
                    
                    # Procura link
                    link = first.select_one("a[href*='MLB']")
                    if link:
                        print(f"   Link: {link.get('href', '')[:80]}...")
                    
                    print()
        
        # ========== TENTANDO EXTRAIR CARDS ==========
        print("="*60)
        print("🔍 EXTRAÇÃO DE CARDS")
        print("="*60 + "\n")
        
        # Tenta seletores conhecidos
        cards = (
            soup.select("li.ui-search-layout__item") or
            soup.select("div.ui-search-result") or
            soup.select("li:has(a[href*='MLB-'])")
        )
        
        print(f"📦 Cards encontrados: {len(cards)}\n")
        
        if cards:
            print("Primeiros 3 cards:\n")
            
            for i, card in enumerate(cards[:3], 1):
                print(f"Card {i}:")
                
                # Link
                link = card.select_one("a[href*='MLB']")
                if link:
                    href = link.get("href", "")
                    print(f"  URL: {href[:80]}...")
                    
                    # Extrai ID
                    import re
                    m = re.search(r'MLB-?(\d+)', href)
                    if m:
                        print(f"  ID: MLB{m.group(1)}")
                
                # Título
                title = card.select_one("h2, .ui-search-item__title")
                if title:
                    print(f"  Título: {title.get_text(strip=True)}")
                
                # Preço
                price = card.select_one(".price-tag-fraction, .ui-search-price__second-line")
                if price:
                    print(f"  Preço: R$ {price.get_text(strip=True)}")
                
                # Localização
                loc = card.select_one(".ui-search-item__location")
                if loc:
                    print(f"  Local: {loc.get_text(strip=True)}")
                
                # Imagem
                img = card.select_one("img")
                if img:
                    img_src = img.get("data-src") or img.get("src") or ""
                    if img_src:
                        print(f"  Imagem: {img_src[:60]}...")
                
                print()
        
        else:
            print("❌ Nenhum card encontrado!")
            print("\nTente inspeção manual:")
            print("1. Abra debug_mercadolivre.html no navegador")
            print("2. F12 → Inspecionar um card de carro")
            print("3. Anote o seletor\n")
        
        # ========== EXPORT ==========
        analysis = {
            "url": url,
            "status": resp.status_code,
            "total_mlb_links": len(mlb_links),
            "total_cards": len(cards),
            "selectors_found": {},
        }
        
        for selector, desc in ml_selectors:
            elements = soup.select(selector)
            if elements:
                analysis["selectors_found"][selector] = {
                    "description": desc,
                    "count": len(elements)
                }
        
        with open("debug_mercadolivre_analysis.json", "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        
        print("💾 Análise salva em: debug_mercadolivre_analysis.json")
        print("\n✅ Debug completo!\n")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    debug_mercadolivre()
