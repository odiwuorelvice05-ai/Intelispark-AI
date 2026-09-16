/* Intelispark AI — account-first onboarding + visual refinement layer. */
(function(){
  document.querySelectorAll('link[href*="Space+Grotesk"]').forEach(el=>el.remove());
  const font=document.createElement('link');font.rel='stylesheet';font.href='https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&display=swap';document.head.appendChild(font);
  const visual=document.createElement('link');visual.rel='stylesheet';visual.href='./design-enhancements.css';document.head.appendChild(visual);

  window.brand=function(){
    return `<div class="brand"><div class="logo" aria-label="Intelispark AI logo"><span class="logo-mark">✦</span></div><div class="brand-name">Intelispark <span>AI</span></div></div>`;
  };

  function cfg(){
    try{return window.INTELISPARK_CONFIG||JSON.parse(localStorage.getItem('intelispark_supabase')||'null');}catch{return window.INTELISPARK_CONFIG||null;}
  }

  window.initSupabase=function(){
    const c=cfg();
    if(!c?.url||!c?.key||!window.supabase){toast('Intelispark is not connected to its data service yet.');return false;}
    if(APP.supabase&&APP.config?.url===c.url&&APP.config?.key===c.key)return true;
    APP.config=c;APP.supabase=window.supabase.createClient(c.url,c.key);return true;
  };

  window.renderAuth=function(){
    document.body.innerHTML=`<div class="auth-wrap"><div class="auth-card">${brand()}
      <h1>${APP.authMode==='signup'?'Create your Intelispark account':'Welcome back'}</h1>
      <p>${APP.authMode==='signup'?'Create your account first. We will set up your business workspace next.':'Sign in first. Your business workspace opens after authentication.'}</p>
      <div class="auth-tabs">
        <button type="button" class="${APP.authMode==='signup'?'active':''}" onclick="APP.authMode='signup';renderAuth()">Sign Up</button>
        <button type="button" class="${APP.authMode==='login'?'active':''}" onclick="APP.authMode='login';renderAuth()">Log In</button>
      </div>
      <form id="authForm" novalidate>
        <div class="field"><label>Email</label><input id="authEmail" type="email" autocomplete="email" required placeholder="you@company.com"></div>
        <div class="field"><label>Password</label><input id="authPassword" type="password" minlength="6" autocomplete="${APP.authMode==='signup'?'new-password':'current-password'}" required placeholder="••••••••"></div>
        <button type="submit" class="primary auth-submit">${APP.authMode==='signup'?'Create account':'Log in'}</button>
      </form>
      <button type="button" class="back-link" onclick="landing()">← Back to Intelispark AI</button>
      <p style="font-size:11px;margin-top:18px;color:#626d80">Account first. Business setup comes after authentication.</p>
    </div></div>`;
    const form=$('#authForm');
    if(form)form.addEventListener('submit',authSubmit);
  };

  window.authSubmit=async function(e){
    e.preventDefault();
    const form=e.currentTarget||$('#authForm');
    const button=form?.querySelector('.auth-submit');
    try{
      if(!initSupabase())return;
      const email=$('#authEmail')?.value.trim()||'';
      const password=$('#authPassword')?.value||'';
      if(!email)return toast('Enter your email address.');
      if(password.length<6)return toast('Password must be at least 6 characters.');
      if(button){button.disabled=true;button.textContent=APP.authMode==='signup'?'Creating account…':'Signing in…';}
      const result=APP.authMode==='login'
        ?await APP.supabase.auth.signInWithPassword({email,password})
        :await APP.supabase.auth.signUp({email,password});
      if(result.error)throw result.error;
      if(APP.authMode==='signup'&&!result.data.session){
        toast('Account created. Check your email to confirm, then log in.');
        APP.authMode='login';
        setTimeout(renderAuth,500);
        return;
      }
      APP.user=result.data.user;
      await enterWorkspace();
    }catch(error){
      console.error('[Intelispark auth]',error);
      toast(error?.message||'Authentication failed. Please try again.');
      if(button){button.disabled=false;button.textContent=APP.authMode==='signup'?'Create account':'Log in';}
    }
  };

  window.enterWorkspace=async function(){
    try{
      if(!APP.supabase&&!initSupabase())return;
      const {data,error}=await APP.supabase.auth.getUser();
      if(error)throw error;
      APP.user=data?.user||APP.user;
      if(!APP.user){renderAuth();return;}
      const ok=await loadBusinessForUser();if(!ok)return;
      if(!APP.business){renderOnboarding();return;}
      await loadData();renderDashboard();
    }catch(error){
      console.error('[Intelispark workspace]',error);
      toast(error?.message||'Could not open your workspace.');
    }
  };

  window.loadBusinessForUser=async function(){
    try{
      const {data,error}=await APP.supabase.from('businesses').select('*').eq('owner_id',APP.user.id).limit(1);
      if(error)throw error;
      APP.business=data?.[0]||null;return true;
    }catch(error){
      console.error('[Intelispark business lookup]',error);
      toast('Could not load your workspace: '+(error?.message||'Unknown error'));
      return false;
    }
  };

  window.renderOnboarding=function(){
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
        <div class="form-actions"><button type="button" class="ghost" onclick="logout()">Sign out</button><button type="submit" class="primary" id="workspaceSubmit">Create my workspace →</button></div>
      </form>
      <p style="font-size:11px;color:#697489;margin-top:20px">You can add products, inventory and deeper business knowledge after the workspace is created.</p>
    </div></div>`;
    const form=$('#onboardingForm');
    if(form)form.addEventListener('submit',createBusiness);
  };

  async function createBusiness(e){
    e.preventDefault();
    const button=$('#workspaceSubmit');
    try{
      if(!APP.supabase&&!initSupabase())return;
      if(!APP.user)throw new Error('Your session has expired. Please sign in again.');
      const f=new FormData(e.currentTarget);
      const payload={owner_id:APP.user.id,name:String(f.get('name')||'').trim(),industry:String(f.get('industry')||'').trim(),phone:String(f.get('phone')||'').trim(),whatsapp_number:String(f.get('whatsapp_number')||'').trim(),email:String(f.get('email')||APP.user.email||'').trim(),timezone:String(f.get('timezone')||'').trim()||'Africa/Nairobi',description:String(f.get('description')||'').trim()};
      if(!payload.name)return toast('Business name is required.');
      if(button){button.disabled=true;button.textContent='Creating workspace…';}
      const {data,error}=await APP.supabase.from('businesses').insert(payload).select().single();
      if(error)throw error;
      APP.business=data;APP.products=[];APP.customers=[];APP.conversations=[];
      toast('Workspace created. Welcome to Intelispark AI.');
      await loadData();renderDashboard();
    }catch(error){
      console.error('[Intelispark workspace creation]',error);
      toast(error?.message||'Could not create workspace.');
      if(button){button.disabled=false;button.textContent='Create my workspace →';}
    }
  }

  window.renderSettings=function(p){
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
      <div class="form-actions"><button type="submit" class="primary">Save business knowledge</button></div></form></div>
      <div class="card form-card" style="margin-top:14px"><div class="section-kicker">CONNECTIONS</div><h3 style="font-family:var(--geist);font-size:20px">Workspace connections</h3><p style="font-size:13px;color:var(--muted);line-height:1.8;margin-top:10px">Database connections are managed by Intelispark. Shop owners do not enter Supabase project URLs, keys or service secrets here.</p><div class="pill" style="margin-top:16px">● Secure connection managed by Intelispark</div></div>`;
    const form=$('#businessForm');
    if(form)form.addEventListener('submit',saveBusiness);
  };

  window.addEventListener('DOMContentLoaded',async()=>{
    if(!initSupabase())return;
    try{
      const {data,error}=await APP.supabase.auth.getSession();
      if(error)throw error;
      if(data.session){APP.user=data.session.user;await enterWorkspace();}
    }catch(error){
      console.error('[Intelispark session]',error);
      toast(error?.message||'Could not restore your session.');
    }
  });
})();
