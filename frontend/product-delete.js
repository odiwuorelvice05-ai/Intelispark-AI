/* Intelispark AI — safe product deletion with tenant-scoped Supabase authorization. */
(function () {
  const originalOpenProductForm = window.openProductForm;

  window.productCards = function (items) {
    if (!items?.length) return `<div class="card empty" style="grid-column:1/-1">No products match your catalog. Add one to begin.</div>`;
    return items.map(x => `<article class="card product-card"><div style="display:flex;justify-content:space-between;gap:8px"><span class="pill">${esc(x.category||'product')}</span><div style="display:flex;gap:8px"><button class="text-btn" onclick='openProductForm(${JSON.stringify(x)})'>Edit</button><button class="text-btn product-delete-btn" type="button" data-product-id="${esc(x.id)}" data-product-name="${esc(x.name||'this product')}">Delete</button></div></div><h3 style="margin-top:18px">${esc(x.name)}</h3><p>${esc([x.brand,x.variant,x.condition].filter(Boolean).join(' • '))}</p><div class="product-meta"><span class="product-price">${money(x.price)}</span><span class="pill ${Number(x.stock_quantity)<3?'warn':''}">${Number(x.stock_quantity||0)} in stock</span></div><p>${esc(x.description||'No description added.')}</p></article>`).join('');
  };

  if (typeof originalOpenProductForm === 'function') {
    window.openProductForm = function (product = null) {
      originalOpenProductForm(product);
      if (!product?.id) return;
      const form = document.querySelector('#productForm');
      if (!form || form.querySelector('.product-delete-btn')) return;
      const actions = document.createElement('div');
      actions.className = 'form-actions product-form-actions';
      actions.innerHTML = `<button class="ghost product-delete-btn" type="button" data-product-id="${esc(product.id)}" data-product-name="${esc(product.name || 'this product')}">Delete product</button>`;
      form.appendChild(actions);
    };
  }

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('.product-delete-btn');
    if (!button) return;
    event.preventDefault();
    if (button.disabled) return;

    const productId = button.dataset.productId;
    const productName = button.dataset.productName || 'this product';
    if (!productId || !APP?.business?.id || !APP?.supabase) return;

    if (!window.confirm(`Delete “${productName}” from your catalog?\n\nThis removes it from Supabase and from Intelispark's active product knowledge. This cannot be undone.`)) return;

    button.disabled = true;
    const previousText = button.textContent;
    button.textContent = 'Deleting…';

    try {
      const session = await APP.supabase.auth.getSession();
      if (!session.data?.session?.access_token) throw new Error('Your session has expired. Please sign in again.');

      /* Supabase is the protected backend for this operation. The products DELETE RLS policy enforces the tenant boundary. */
      const result = await APP.supabase.from('products').delete().eq('id', productId).eq('business_id', APP.business.id).select('id').maybeSingle();
      if (result.error) throw result.error;
      if (!result.data) throw new Error('Product could not be deleted or was already removed.');

      await loadData();
      renderTab();
      toast('Product deleted successfully.');
    } catch (error) {
      button.disabled = false;
      button.textContent = previousText;
      toast(error.message || 'Could not delete product.');
    }
  });
})();
