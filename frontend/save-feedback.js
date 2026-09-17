/* Intelispark AI — reliable product mutation UX.
   The original product mutation remains the source of truth; this layer adds
   deterministic busy-state protection, success/error feedback, persistence
   verification, and a live catalog refresh for both create and update. */
(function(){
  const originalOpenProductForm=window.openProductForm;
  const wrappedForms=new WeakSet();
  let activeForm=null;

  function setBusy(form,busy,label='Saving product…'){
    if(!form)return;
    const button=form.querySelector('button[type="submit"]');
    if(button){
      button.disabled=busy;
      button.setAttribute('aria-busy',busy?'true':'false');
      if(busy){
        button.dataset.originalLabel=button.textContent||'Save Product';
        button.textContent=label;
      }else{
        button.removeAttribute('aria-busy');
        button.textContent=button.dataset.originalLabel||'Save Product';
        delete button.dataset.originalLabel;
      }
    }
    form.setAttribute('aria-busy',busy?'true':'false');
  }

  function formValues(form){
    const data=new FormData(form);
    const value=name=>String(data.get(name)??'').trim();
    const rawPrice=value('price');
    const rawStock=value('stock_quantity');
    let specs={};
    const rawSpecs=value('specs');
    if(rawSpecs){
      try{specs=JSON.parse(rawSpecs);}
      catch{specs={notes:rawSpecs};}
    }
    return {
      name:value('name'),
      brand:value('brand')||null,
      category:value('category')||'other',
      variant:value('variant')||null,
      condition:value('condition')||'new',
      price:rawPrice===''?null:Number(rawPrice),
      stock_quantity:rawStock===''?0:Math.max(0,Math.trunc(Number(rawStock))),
      description:value('description')||null,
      specs,
      installment_available:Boolean(form.elements.installment_available?.checked||form.elements.installmentAvailable?.checked)
    };
  }

  async function verifySaved(businessId,productId,expected){
    if(productId){
      const result=await APP.supabase.from('products').select('*').eq('id',productId).eq('business_id',businessId).maybeSingle();
      if(result.error)throw result.error;
      if(!result.data)throw new Error('The product update could not be confirmed.');
      const row=result.data;
      const matches=row.name===expected.name && Number(row.stock_quantity)===expected.stock_quantity && Number(row.price??0)===Number(expected.price??0);
      if(!matches)throw new Error('The product was not saved with the latest values.');
      return row;
    }

    const result=await APP.supabase.from('products').select('*').eq('business_id',businessId).eq('name',expected.name).order('created_at',{ascending:false}).limit(1).maybeSingle();
    if(result.error)throw result.error;
    if(!result.data)throw new Error('The new product could not be confirmed in the catalog.');
    return result.data;
  }

  function wrapForm(form,product){
    if(!form||wrappedForms.has(form))return;
    const originalHandler=form.onsubmit;
    if(typeof originalHandler!=='function')return;
    wrappedForms.add(form);
    form.onsubmit=async function(event){
      if(activeForm===form){
        event.preventDefault();
        toast('Product is still being saved…');
        return false;
      }
      activeForm=form;
      event.preventDefault();
      const businessId=APP?.business?.id;
      if(!APP?.supabase||!businessId){
        activeForm=null;
        toast('Your shop workspace is not ready. Please refresh and try again.');
        return false;
      }

      const expected=formValues(form);
      if(!expected.name){
        activeForm=null;
        toast('Product name is required.');
        form.querySelector('[name="name"]')?.focus();
        return false;
      }
      if(!Number.isFinite(expected.price) && expected.price!==null){
        activeForm=null;
        toast('Enter a valid product price.');
        return false;
      }
      if(!Number.isFinite(expected.stock_quantity)){
        activeForm=null;
        toast('Enter a valid stock quantity.');
        return false;
      }

      const editingId=product?.id||null;
      setBusy(form,true,editingId?'Updating product…':'Saving product…');
      try{
        /* Run the existing mutation exactly once. */
        const result=await originalHandler.call(form,event);
        if(result?.error)throw result.error;

        await verifySaved(businessId,editingId,expected);
        await loadData();
        APP.tab='products';
        renderTab();
        toast(editingId?'Product updated successfully.':'Product added successfully.');
      }catch(error){
        console.error('[Intelispark product mutation]',error);
        setBusy(form,false,editingId?'Update Product':'Save Product');
        toast(error?.message||`Could not ${editingId?'update':'save'} the product.`);
      }finally{
        activeForm=null;
      }
      return false;
    };
  }

  if(typeof originalOpenProductForm==='function'){
    window.openProductForm=function(product=null){
      originalOpenProductForm(product);
      wrapForm(document.querySelector('#productForm'),product);
    };
  }
})();