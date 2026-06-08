"""
Acoes operacionais por Nivel de Operacao (PPDC / SAMAEG).

Fonte: Quadro 4.2.2-2 do Produto 7 (Plano de Contingencia),
Relatorio 2053-R04-21, Etapa 3.

Os niveis seguem a estrutura do PPDC - Plano Preventivo de Defesa Civil,
operado pela CEPDEC durante o periodo chuvoso (dez-mar).
"""

from typing import List, Dict

NIVEL_ACOES = {
    0: {  # Monitoramento
        "nivel": "Monitoramento",
        "cor": "#22c55e",
        "descricao": "Monitoramento automatico pelo SAMAEG",
        "acoes": [
            "COI-DER/SP: monitoramento das condicoes de chuvas e mudancas de nivel",
            "CCO/UBA-DER/SP: monitoramento complementar das condicoes",
            "CEPDEC: acompanhamento do monitoramento",
        ],
        "responsavel_principal": "COI - DER/SP",
        "prontidao": False,
        "vistoria": False,
    },
    1: {  # Observacao
        "nivel": "Observação",
        "cor": "#eab308",
        "descricao": "Monitoramento e prontidao de equipes de emergencia",
        "acoes": [
            "COI-DER/SP: comunicar ao CCO o inicio do nivel em Observacao",
            "COI-DER/SP: continuidade do monitoramento das chuvas",
            "CCO-DER/SP: iniciar nivel em Observacao na regiao da UBA",
            "UBA-DER/SP: atender ao nivel, permanecer a disposicao do CCO",
            "CEPDEC: continuidade do monitoramento das condicoes de chuvas",
        ],
        "responsavel_principal": "COI - DER/SP",
        "prontidao": True,
        "vistoria": False,
    },
    2: {  # Atencao
        "nivel": "Atenção",
        "cor": "#f97316",
        "descricao": "Vistorias expeditas e prontidao das equipes",
        "acoes": [
            "COI-DER/SP: comunicar ao CCO o inicio do nivel em Atencao",
            "COI-DER/SP: continuidade do monitoramento das chuvas",
            "CCO-DER/SP: iniciar nivel em Atencao, solicitar prontidao das equipes da UBA",
            "UBA-DER/SP: posicionar equipes para prontidao aos acionamentos",
            "UBA-DER/SP: iniciar vistorias expeditas, priorizando trechos criticos",
            "PM Rodoviaria: informes complementares sobre condicoes da via",
            "CEPDEC: acompanhamento e apoio ao monitoramento",
        ],
        "responsavel_principal": "COI / CCO - DER/SP",
        "prontidao": True,
        "vistoria": True,
    },
    3: {  # Alerta
        "nivel": "Alerta",
        "cor": "#ef4444",
        "descricao": "Vistorias em campo obrigatorias nos trechos criticos",
        "acoes": [
            "COI-DER/SP: comunicar ao CCO o inicio do nivel em Alerta",
            "COI-DER/SP: continuidade do monitoramento e acionamento de outros orgaos",
            "CCO-DER/SP: mobilizar equipes de conservacao para vistorias",
            "UBA-DER/SP: vistorias em campo obrigatorias nos trechos criticos",
            "UBA-DER/SP: em caso de confirmacao de desastre, acionar Plano de Contingencia",
            "PM Rodoviaria: apoio ao controle de trafego e sinalizacao",
            "CEPDEC: alerta as Defesas Civis municipais da area de abrangencia",
        ],
        "responsavel_principal": "UBA / CCO - DER/SP",
        "prontidao": True,
        "vistoria": True,
    },
    4: {  # Alerta Maximo
        "nivel": "Alerta Máximo",
        "cor": "#a855f7",
        "descricao": "Vistorias intensivas e acionamento do Plano de Contingencia",
        "acoes": [
            "COI-DER/SP: comunicar Alerta Maximo e acionar todos os orgaos envolvidos",
            "CCO-DER/SP: mobilizar equipes de conservacao e apoio emergencial",
            "UBA-DER/SP: vistorias intensivas em todos os trechos criticos",
            "UBA-DER/SP: confirmacao de ocorrencia -> acionamento PLANO DE CONTINGENCIA",
            "UBA-DER/SP: solicitar complementacao de equipes e equipamentos das UBAs vizinhas",
            "PM Rodoviaria: controle de trafego, interdicao se necessario, sinalizacao",
            "CEPDEC: acionamento do PPDC municipal, retirada preventiva se necessario",
            "Saude/Resgate: prontidao para atendimento de vitimas",
        ],
        "responsavel_principal": "UBA / CCO / COI - DER/SP",
        "prontidao": True,
        "vistoria": True,
    },
}


def get_actions_for_level(rd: int) -> Dict:
    """Retorna dict com acoes para um nivel RD (0..4)."""
    return NIVEL_ACOES.get(max(0, min(4, rd)), NIVEL_ACOES[0])


def parse_acao(acao: str) -> Dict[str, str]:
    """Separa uma acao no formato 'ORGAO: texto' em {orgao, texto}.

    Quando nao ha prefixo de orgao, retorna orgao vazio e o texto integral.
    """
    if ":" in acao:
        orgao, texto = acao.split(":", 1)
        return {"orgao": orgao.strip(), "texto": texto.strip()}
    return {"orgao": "", "texto": acao.strip()}


def get_protocolo_completo() -> List[Dict]:
    """Protocolo PPDC completo (todos os 5 niveis) para pagina de referencia.

    Cada nivel traz as acoes ja separadas por orgao responsavel.
    """
    out: List[Dict] = []
    for rd in range(5):
        nivel = NIVEL_ACOES[rd]
        out.append({
            "rd": rd,
            "nivel": nivel["nivel"],
            "cor": nivel["cor"],
            "descricao": nivel["descricao"],
            "responsavel_principal": nivel["responsavel_principal"],
            "prontidao": nivel["prontidao"],
            "vistoria": nivel["vistoria"],
            "acoes": [parse_acao(a) for a in nivel["acoes"]],
        })
    return out


def get_actions_for_point(point: Dict) -> Dict:
    """Retorna acoes para o nivel atual de um ponto (do snapshot)."""
    rd = point.get("rd", 0)
    actions = get_actions_for_level(rd)
    actions["ponto"] = point.get("nome", "")
    actions["rodovia"] = point.get("rodovia", "")
    actions["km"] = point.get("km", "")
    actions["rd"] = rd
    actions["nivel_atual"] = point.get("nivel", "Monitoramento")
    return actions


def get_summary_actions(snapshot_points: List[Dict]) -> Dict:
    """
    Retorna resumo das acoes necessarias para todo o snapshot.
    Usado pelo frontend para painel de operacoes.
    """
    max_rd = max((p.get("rd", 0) for p in snapshot_points), default=0)
    max_actions = get_actions_for_level(max_rd)

    # Pontos em nivel critico (>=3)
    critical = [p for p in snapshot_points if p.get("rd", 0) >= 3]
    # Pontos em atencao (==2)
    warning = [p for p in snapshot_points if p.get("rd", 0) == 2]

    def _resumo(p: Dict) -> Dict:
        return {
            "nome": p.get("nome"),
            "rd": p.get("rd"),
            "nivel": p.get("nivel"),
            "rodovia": p.get("rodovia"),
            "km": p.get("km"),
            "regiao": p.get("region_name"),
            "ac24h_mm": p.get("ac24h_mm"),
            "ac96h_mm": p.get("ac96h_mm"),
        }

    # Ordena os trechos do mais grave para o menos grave
    crit_sorted = sorted(
        critical, key=lambda p: p.get("rd", 0), reverse=True
    )
    warn_sorted = sorted(
        warning, key=lambda p: p.get("ac24h_mm", 0) or 0, reverse=True
    )

    return {
        "max_rd": max_rd,
        "max_nivel": max_actions["nivel"],
        "max_cor": max_actions["cor"],
        "max_descricao": max_actions["descricao"],
        "acoes_max": max_actions["acoes"],
        "acoes_max_estruturadas": [
            parse_acao(a) for a in max_actions["acoes"]
        ],
        "responsavel_max": max_actions["responsavel_principal"],
        "vistoria_necessaria": max_actions["vistoria"],
        "prontidao_necessaria": max_actions["prontidao"],
        # Acao e demandada (alem do monitoramento de rotina) a partir do
        # nivel 1 (Observacao). Usado para acender o botao no frontend.
        "acoes_necessarias": max_rd >= 1,
        "pontos_criticos": [_resumo(p) for p in crit_sorted],
        "pontos_atencao": [_resumo(p) for p in warn_sorted],
        "total_pontos": len(snapshot_points),
        "total_critico": len(critical),
        "total_atencao": len(warning),
    }
