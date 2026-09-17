/* Intelispark AI — persistence confirmations. Confirms successful database writes before showing success feedback. */
(function(){
  async function confirmProductSave(form){
    try{
      if(!APP?.supabase||!APP?.business?.id)return;
      const businessId=APP.business.id;
      const name=String(form.querySelector('[name="name"]')?.value||'').trim();
      const beforeResult=await APP.supabase.from('products').select('id,name,updated_at,created_at').eq('business_id',businessId);
      if(beforeResult.error)return;
      const before=new Map((beforeResult.data||[]).map(x=>[x.id,x]));
      const started=Date.now();
      const check=async()=>{
        const result=await APP.supabase.from('products').select('id,name,updated_at,created_at').eq('business_id',businessId);
        if(result.error)throw result.error;
        const rows=result.data||[];
        const added=rows.find(x=>!before.has(x.id));
        if(added){toast('Added Successfully.');return true;}
        const changed=rows.find(x=>before.has(x.id)&&x.name===name&&String(x.updated_at||'')!==String(before.get(x.id)?.updated_at||''));
        if(changed){toast('Saved Successfully.');return true;}
        if(Date.now()-started<6000){setTimeout(check,500);return false;}
        return false;
      };
      setTimeout(()=>check().catch(error=>console.error('[Intelispark save confirmation]',error)),700);
    }catch(error){console.error('[Intelispark save confirmation]',error)}
  }

  document.addEventListener('submit',event=>{
    const form=event.target;
    if(form?.id==='productForm')confirmProductSave(form);
  },true);
})();
