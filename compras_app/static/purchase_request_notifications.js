(() => {
const badges=document.querySelectorAll("[data-pr-notification]");
if(!badges.length)return;
async function refresh(){
 if(document.hidden)return;
 try{
  const response=await fetch("/api/erp/purchase-requests/notifications",{headers:{"Accept":"application/json"}});
  const data=await response.json();
  if(!response.ok||!data.ok)throw new Error();
  badges.forEach(n=>{n.textContent="("+data.new+" novas · "+data.in_progress+" em compras)";n.title="Solicitações pendentes de conclusão de compras";});
 }catch(e){badges.forEach(n=>{n.textContent="";n.title="Notificações temporariamente indisponíveis";});}
}
refresh();setInterval(refresh,60000);
})();
