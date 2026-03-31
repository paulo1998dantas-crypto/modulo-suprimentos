def calcular_total_item(qtd, valor, desconto, ipi=0, icms=0, cofins=0):
    qtd = float(qtd) if qtd else 0
    valor = float(valor) if valor else 0
    desconto = float(desconto) if desconto else 0
    ipi = float(ipi) if ipi else 0
    icms = float(icms) if icms else 0
    cofins = float(cofins) if cofins else 0

    base = (qtd * valor) - desconto
    if base <= 0:
        return 0
    percentual = (ipi + icms + cofins) / 100
    return base * (1 + percentual)


def calcular_totais(itens, frete, despesas):

    frete = float(frete) if frete else 0
    despesas = float(despesas) if despesas else 0

    total_itens = 0

    for item in itens:
        total_itens += item["total"]

    valor_total_sem_frete = total_itens + despesas
    valor_total_pedido = total_itens + frete + despesas

    return {
        "total_itens": total_itens,
        "valor_total_sem_frete": valor_total_sem_frete,
        "valor_total_pedido": valor_total_pedido
    }
