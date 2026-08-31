from __future__ import annotations

STATE_NAME_TO_UF: dict[str, str] = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES",
    "goias": "GO", "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS",
    "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO",
    "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

KNOWN_STATES_UF: frozenset[str] = frozenset(STATE_NAME_TO_UF.values())

# Capital city per UF. Used as a proxy location when a wishlist only specifies
# a state (no city) and a source needs a concrete city to search by.
UF_TO_CAPITAL: dict[str, str] = {
    "AC": "Rio Branco", "AL": "Maceio", "AP": "Macapa", "AM": "Manaus",
    "BA": "Salvador", "CE": "Fortaleza", "DF": "Brasilia", "ES": "Vitoria",
    "GO": "Goiania", "MA": "Sao Luis", "MT": "Cuiaba", "MS": "Campo Grande",
    "MG": "Belo Horizonte", "PA": "Belem", "PB": "Joao Pessoa", "PR": "Curitiba",
    "PE": "Recife", "PI": "Teresina", "RJ": "Rio de Janeiro",
    "RN": "Natal", "RS": "Porto Alegre", "RO": "Porto Velho",
    "RR": "Boa Vista", "SC": "Florianopolis", "SP": "Sao Paulo",
    "SE": "Aracaju", "TO": "Palmas",
}
