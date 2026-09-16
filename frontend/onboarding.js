/* Intelispark AI — account-first onboarding layer. */
(function(){
  const originalRenderSettings = window.renderSettings;
  const originalEnterWorkspace = window.enterWorkspace;
  const originalLoadBusinessForUser = window.loadBusinessForUser;

  function cfg(){
    try { return JSON.parse(localStorage.getItem('intelispark_supabase') || 'null'); } catch { return null; }
  }

  window.initSupabase = function(){
    const c = cfg();
    if (!c?.url || !c?.key || !window.supabase) {
      toast('Intelispark is not connected to its data service yet.');
      return false;
    }
    APP.config = c;
    APP.supabase = window.supabase.createClient(c.url, c.key);
    return true;
  };

  window.renderAuth = function(){
    document.body.innerHTML = `<div class="auth-wrap"><div class="auth-card">${brand()}
      <h1>${APP.authMode==='login'?'Welcome back':'Create your Intelispark account'}</h1>
      <p>${APP.authMode==='login'?'Sign in first. Your business workspace opens after authentication.':'Create your account first. We will set up your business workspace next.'}</p>
      <div class="auth-tabs">
        <button class="${APP.authMode==='login'?'active':''}" onclick="APP.authMode='login';renderAuth()">Sign in</button>
        <button class="${APP.authMode==='signup'?'active':''}" onclick="APP.authMode='signup';renderAuth()">Create account</button>
      </div>
      <form id="authForm">
        <div class="field"><label>Email</label><input id="authEmail" type="email" autocomplete="email" required placeholder="you@company.com"></div>
        <div class="field"><label>Password</label><input id="authPassword" type="password" minlength="6" autocomplete="new-password" required placeholder="••••••••"></div>
        <button class="primary auth-submit">${APP.authMode==='login'?'Sign in':'Create account'}</button>
      </form>
      <button class="back-link" onclick="landing()">← Back to Intelispark AI</button>
      <p style="font-size:11px;margin-top:18px;color:#626d80">Account first. Business setup comes after authentication.</p>
    </div></div>`;
    $('#authForm').onsubmit = authSubmit;
  };

  window.authSubmit = async function(e){
    e.preventDefault();
    if(!initSupabase()) return;
    const email=$('#authEmail').value.trim();
    const password=$('#authPassword').value;
    const result = APP.authMode==='login'
      ? await APP.supabase.auth.signInWithPassword({email,password})
      : await APP.supabase.auth.signUp({email,password});
    if(result.error){ toast(result.error.message); return; }
    if(APP.authMode==='signup' && !result.data.session){
      toast('Account created. Check your email to confirm, then sign in.');
      APP.authMode='login';
      renderAuth();
      return;
    }
    APP.user=result.data.user;
    await enterWorkspace();
  };

  window.enterWorkspace = async function(){
    if(!APP.supabase && !initSupabase()) return;
    const {data:{user}}=await APP.supabase.auth.getUser();
    APP.user=user||APP.user;
    if(!APP.user){renderAuth();return;}
    const ok=await loadBusinessForUser();
    if(!ok) return;
    if(!APP.business){
      renderOnboarding();
      return;
    }
    await loadData();
    renderDashboard();
  };

  window.loadBusinessForUser = async function(){
    const {data,error}=await APP.supabase.from('businesses').select('*').eq('owner_id',APP.user.id).limit(1);
    if(error){toast('Could not load your workspace: '+error.message);return false;}
    APP.business=data?.[0]||null;
    return true;
  };

  window.renderOnboarding = function(){
    document.body.innerHTML=`<div class="auth-wrap"><div class="auth-card" style="max-width:720px">${brand()}
      <div class="section-kicker" style="margin-top:28px">STEP 2 / BUSINESS ONBOARDING</div>
      <h1>Teach Intelispark about your business.</h1>
      <p>Now that your account is secure, add the business facts Intelispark will use as its source of truth. No Supabase credentials are required here.</p>
      <form id="onboardingForm" class="form-card" style="padding:0;background:transparent;border:0;box-shadow:none">
        <div class="grid form-grid">
          <div class="field"><label>Business name *</label><input name="name" required placeholder="Your shop or company"></div>
          <div class="field"><label>Industry</label><input name="industry" placeholder="Retail, electronics, services…"></div>
          <div class="field"><label>Business phone</label><input name="phone" placeholder="Business phone number"></div>
          <div class="field"><label>WhatsApp number</label><input name="whatsapp_number" placeholder="Number customers use on WhatsApp"></div>
          <div class="field"><label>Business email</label><input name="email" type="email" value="${esc(APP.user?.email||'')}"></div>
          <div class="field"><label>Timezone</label><input name="timezone" value="Africa/Nairobi"></div>
        </div>
        <div class="field"><label>Business description & policies</label><textarea name="description" rows="6" placeholder="Opening hours, delivery, warranty, returns, payment methods, location, sales policies and anything Intelispark should know…"></textarea></div>
        <div class="form-actions"><button type="button" class="ghost" onclick="logout()">Sign out</button><button class="primary">Create my workspace →</button></div>
      </form>
      <p style="font-size:11px;color:#697489;margin-top:20px">You can add products, inventory and deeper business knowledge after the workspace is created.</p>
    </div></div>`;
    $('#onboardingForm').onsubmit=createBusiness;
  };

  async function createBusiness(e){
    e.preventDefault();
    const f=new FormData(e.target);
    const payload={
      owner_id:APP.user.id,
      name:String(f.get('name')||'').trim(),
      industry:String(f.get('industry')||'').trim(),
      phone:String(f.get('phone')||'').trim(),
      whatsapp_number:String(f.get('whatsapp_number')||'').trim(),
      email:String(f.get('email')||APP.user.email||'').trim(),
      timezone:String(f.get('timezone')||'Africa/Nairobi').trim(),
      description:String(f.get('description')||'').trim()
    };
    if(!payload.name) return toast('Business name is required.');
    const {data,error}=await APP.supabase.from('businesses').insert(payload).select().single();
    if(error){toast('Could not create workspace: '+error.message);return;}
    APP.business=data;
    APP.products=[];APP.customers=[];APP.conversations=[];
    toast('Workspace created. Welcome to Intelispark AI.');
    await loadData();
    renderDashboard();
  }

  window.renderSettings = function(p){
    p.innerHTML=head('Settings','Manage your business knowledge and workspace preferences.')+
      `<div class="card form-card"><div class="section-kicker">BUSINESS PROFILE</div>
      <form id="businessForm"><div class="grid form-grid">
      <div class="field"><label>Business name</label><input name="name" value="${esc(APP.business?.name)}" required></div>
      <div class="field"><label>Industry</label><input name="industry" value="${esc(APP.business?.industry)}" placeholder="Retail"></div>
      <div class="field"><label>Business phone</label><input name="phone" value="${esc(APP.business?.phone)}"></div>
      <div class="field"><label>WhatsApp number</label><input name="whatsapp_number" value="${esc(APP.business?.whatsapp_number)}"></div>
      <div class="field"><label>Business email</label><input name="email" type="email" value="${esc(APP.business?.email)}"></div>
      <div class="field"><label>Timezone</label><input name="timezone" value="${esc(APP.business?.timezone||'Africa/Nairobi')}"></div>
      </div><div class="field"><label>Business description / policies</label><textarea name="description" rows="6" placeholder="Opening hours, delivery policy, warranty, returns, payment methods, sales rules…">${esc(APP.business?.description)}</textarea></div>
      <div class="form-actions"><button class="primary">Save business knowledge</button></div></form></div>
      <div class="card form-card" style="margin-top:14px"><div class="section-kicker">CONNECTIONS</div><h3 style="font-family:'Space Grotesk';font-size:20px">Workspace connections</h3><p style="font-size:13px;color:var(--muted);line-height:1.8;margin-top:10px">Database connections are managed by Intelispark. Shop owners do not enter Supabase project URLs, keys or service secrets here.</p><div class="pill" style="margin-top:16px">● Secure connection managed by Intelispark</div></div>`;
    $('#businessForm').onsubmit=saveBusiness;
  };

  window.addEventListener('DOMContentLoaded',async()=>{
    if(!initSupabase()) return;
    const {data}=await APP.supabase.auth.getSession();
    if(data.session){APP.user=data.session.user;await enterWorkspace();}
  });
})();
