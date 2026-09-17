/* Intelispark AI — safe product deletion with tenant-scoped Supabase authorization. */
(function () {
  const originalProductCards = window.productCards;
  const originalOpenProductForm = window.openProductForm;

  if (typeof originalProductCards === 'function') {
    window.productCards = function (items) {
      const html = originalProductCards(items);
      if (!items?.length) return html;
      return html.replace(/<button class="text-btn" onclick='openProductForm\((\{.*?\})\)'>Edit<\/button>/g, (match, productJson) => {
        let id = '';
        try { id = JSON.parse(productJson).id || ''; } catch (_) {}
        return `${match}<button class="text-btn product-delete-btn" type="button" data-product-id="${esc(id)}" data-product-name="${esc(JSON.parse(productJson).name || 'this product')}">Delete</button>`;
      });
    };
  }

  if (typeof originalOpenProductForm === 'function') {
    window.openProductForm = function (product = null) {
      originalOpenProductForm(product);
      if (!product?.id) return;
      const form = document.querySelector('#productForm');
      if (!form || form.querySelector('.delete-product-btn')) return;
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

    const confirmed = window.confirm(`Delete “${productName}” from your catalog?\n\nThis removes the product from Supabase and from Intelispark's active product knowledge. This cannot be undone.`);
    if (!confirmed) return;

    button.disabled = true;
    const previousText = button.textContent;
    button.textContent = 'Deleting…';

    try {
      const session = await APP.supabase.auth.getSession();
      const token = session.data?.session?.access_token;
      if (!token) throw new Error('Your session has expired. Please sign in again.');

      /* Supabase is the protected backend here: the products DELETE policy enforces the tenant boundary. */
      const result = await APP.supabase
        .from('products')
        .delete()
        .eq('id', productId)
        .eq('business_id', APP.business.id)
        .select('id')
        .maybeSingle();

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
