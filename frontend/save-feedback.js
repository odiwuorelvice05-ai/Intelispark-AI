/* Intelispark AI — persistence confirmations and duplicate-submit protection. */
(function(){
  let activeForm = null;

  async function confirmProductSave(form){
    if(!APP?.supabase||!APP?.business?.id)return;
    const businessId=APP.business.id;
    const name=String(form.querySelector('[name="name"]')?.value||'').trim();
    const price=String(form.querySelector('[name="price"]')?.value||'');
    const stock=String(form.querySelector('[name="stock_quantity"]')?.value||'0');
    const button=form.querySelector('button[type="submit"]');
    const started=Date.now();

    const check=async()=>{
      const result=await APP.supabase.from('products').select('id,name,price,stock_quantity,updated_at,created_at').eq('business_id',businessId).order('created_at',{ascending:false}).limit(20);
      if(result.error)throw result.error;
      const rows=result.data||[];
      const match=rows.find(x=>String(x.name||'').trim()===name && String(x.price??'')===price && String(x.stock_quantity??0)===stock);
      if(match){
        toast('Product added successfully.');
        if(button){button.disabled=false;button.removeAttribute('aria-busy');button.textContent='Product added ✓';}
        activeForm=null;
        setTimeout(()=>{if(button&&document.body.contains(button))button.textContent='Save Product';},1800);
        return true;
      }
      if(Date.now()-started<8000){setTimeout(check,400);return false;}
      if(button){button.disabled=false;button.removeAttribute('aria-busy');button.textContent='Save Product';}
      activeForm=null;
      toast('We could not confirm the product was saved. Please try again.');
      return false;
    };
    setTimeout(check,700);
  }

  document.addEventListener('submit',event=>{
    const form=event.target;
    if(form?.id!=='productForm')return;
    if(activeForm===form){
      event.preventDefault();
      toast('Product is still being saved…');
      return;
    }
    activeForm=form;
    const button=form.querySelector('button[type="submit"]);
    if(button){
      button.disabled=true;
      button.setAttribute('aria-busy','true');
      button.textContent='Saving product…';
    }
    confirmProductSave(form).catch(error=>{
      console.error('[Intelispark product save]',error);
      if(button){button.disabled=false;button.removeAttribute('aria-busy');button.textContent='Save Product';}
      activeForm=null;
      toast('Product save could not be confirmed.');
    });
  },true);
})();
