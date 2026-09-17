/* Intelispark AI — reliable product-save feedback and duplicate-submit protection. */
(function(){
  let activeForm=null;

  async function waitForProductPersistence(businessId,baselineCount,button){
    const started=Date.now();
    while(Date.now()-started<10000){
      const result=await APP.supabase.from('products').select('id',{count:'exact',head:true}).eq('business_id',businessId);
      if(result.error)throw result.error;
      const currentCount=Number(result.count||0);
      if(currentCount>baselineCount){
        toast('Product added successfully.');
        if(button&&document.body.contains(button)){
          button.disabled=false;
          button.removeAttribute('aria-busy');
          button.textContent='Product added ✓';
          setTimeout(()=>{if(document.body.contains(button))button.textContent='Save Product';},1800);
        }
        activeForm=null;
        return true;
      }
      await new Promise(resolve=>setTimeout(resolve,350));
    }
    if(button&&document.body.contains(button)){
      button.disabled=false;
      button.removeAttribute('aria-busy');
      button.textContent='Save Product';
    }
    activeForm=null;
    toast('We could not confirm the product was saved. Please check your catalog.');
    return false;
  }

  document.addEventListener('submit',async event=>{
    const form=event.target;
    if(form?.id!=='productForm')return;
    if(activeForm===form){
      event.preventDefault();
      toast('Product is still being saved…');
      return;
    }

    activeForm=form;
    const button=form.querySelector('button[type="submit"]');
    const businessId=APP?.business?.id;
    if(!APP?.supabase||!businessId){
      activeForm=null;
      return;
    }

    try{
      const before=await APP.supabase.from('products').select('id',{count:'exact',head:true}).eq('business_id',businessId);
      if(before.error)throw before.error;
      const baselineCount=Number(before.count||0);
      if(button){
        button.disabled=true;
        button.setAttribute('aria-busy','true');
        button.textContent='Saving product…';
      }
      waitForProductPersistence(businessId,baselineCount,button).catch(error=>{
        console.error('[Intelispark product save confirmation]',error);
        if(button&&document.body.contains(button)){
          button.disabled=false;
          button.removeAttribute('aria-busy');
          button.textContent='Save Product';
        }
        activeForm=null;
        toast(error?.message||'Product save could not be confirmed.');
      });
    }catch(error){
      console.error('[Intelispark product save feedback]',error);
      if(button){button.disabled=false;button.removeAttribute('aria-busy');button.textContent='Save Product';}
      activeForm=null;
      toast(error?.message||'Could not prepare product save.');
    }
  },true);
})();