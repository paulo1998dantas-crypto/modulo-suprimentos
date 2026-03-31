function addItem() {

    let tabela = document.getElementById("itens")

    let row = tabela.insertRow()

    row.innerHTML = `
    <td><input name="codigo[]" required></td>
    <td><input name="descricao[]" required></td>
    <td><input name="unidade[]" value="UN"></td>
    <td><input name="qtd[]" type="number"></td>
    <td><input name="valor[]" type="number" step="0.01"></td>
    <td><input name="desconto[]" type="number" step="0.01" value="0"></td>
    <td></td>
    `
}