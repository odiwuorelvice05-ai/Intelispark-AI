/* Intelispark AI — persistent customer conversation interface. */
(function(){
  const BACKEND='/api';
  let activeConversationId=null;
  let activeMessages=[];

  function formatTime(value){
    if(!value)return '';
    try{return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}catch(_){return '';}
  }

  async function getMessages(conversationId){
    if(!APP?.supabase||!conversationId)return [];
    const result=await APP.supabase.from('messages').select('id,sender_type,message_text,channel,created_at').eq('conversation_id',conversationId).order('created_at',{ascending:true});
    if(result.error)throw result.error;
    return result.data||[];
  }

  function messageBubble(message){
    const customer=message.sender_type==='customer';
    return `<div class="chat-row ${customer?'customer':'assistant'}"><div class="chat-avatar">${customer?'You':'I'}</div><div class="chat-bubble"><div class="chat-text">${esc(message.message_text)}</div><span class="chat-time">${formatTime(message.created_at)}</span></div></div>`;
  }

  function conversationList(){
    if(!APP.conversations.length)return '<div class="empty">No customer conversations yet. Run a message in the intelligence workspace to create one.</div>';
    return APP.conversations.map(c=>`<button type="button" class="conversation-item ${activeConversationId===c.id?'active':''}" data-conversation-id="${esc(c.id)}"><span class="conversation-icon">◌</span><span><b>Customer conversation</b><small>${esc(c.channel||'whatsapp')} · ${c.last_message_at?formatTime(c.last_message_at):'No messages yet'}</small></span></button>`).join('');
  }

  async function selectConversation(id){
    activeConversationId=id;
    const area=$('#conversationMessages');
    if(area)area.innerHTML='<div class="chat-loading">Loading conversation…</div>';
    try{
      activeMessages=await getMessages(id);
      if(area)area.innerHTML=activeMessages.length?activeMessages.map(messageBubble).join(''):'<div class="empty">No messages in this conversation yet.</div>';
      area?.scrollTo({top:area.scrollHeight,behavior:'smooth'});
      document.querySelectorAll('.conversation-item').forEach(x=>x.classList.toggle('active',x.dataset.conversationId===id));
    }catch(error){if(area)area.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load conversation.')}</div>`;}
  }

  async function refreshConversationList(){
    await loadData();
    const list=$('#conversationList');
    if(list)list.innerHTML=conversationList();
    document.querySelectorAll('.conversation-item').forEach(item=>item.addEventListener('click',()=>selectConversation(item.dataset.conversationId)));
    if(activeConversationId)await selectConversation(activeConversationId);
  }

  async function sendMessage(event){
    event.preventDefault();
    const input=$('#conversationInput'),button=$('#conversationSend'),message=input?.value.trim();
    if(!message||!APP.business||!APP.user)return;
    button.disabled=true;button.textContent='Thinking…';
    const temporary={id:`temp-${Date.now()}`,sender_type:'customer',message_text:message,created_at:new Date().toISOString()};
    const area=$('#conversationMessages');
    if(area){area.insertAdjacentHTML('beforeend',messageBubble(temporary));area.scrollTo({top:area.scrollHeight,behavior:'smooth'});}
    input.value='';
    try{
      const session=await APP.supabase.auth.getSession(),token=session.data?.session?.access_token;
      if(!token)throw new Error('Your session has expired. Please sign in again.');
      const response=await fetch(`${BACKEND}/sales/reply`,{method:'POST',headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`},body:JSON.stringify({business_id:APP.business.id,customer_message:message})});
      const payload=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(payload.detail||`Intelligence request failed (${response.status}).`);
      activeConversationId=payload.conversation_id||activeConversationId;
      activeMessages=await getMessages(activeConversationId);
      if(area)area.innerHTML=activeMessages.map(messageBubble).join('');
      if(area)area.scrollTo({top:area.scrollHeight,behavior:'smooth'});
      await refreshConversationList();
    }catch(error){
      if(area){area.insertAdjacentHTML('beforeend',`<div class="ai-error">${esc(error.message||'Could not send message.')}</div>`);area.scrollTo({top:area.scrollHeight,behavior:'smooth'});}
    }finally{button.disabled=false;button.textContent='Send';input?.focus();}
  }

  window.renderAI=function(p){
    p.innerHTML=head('Test Intelispark','Talk to the intelligence engine as a customer. Every message is grounded in this shop’s Supabase catalog and saved to Conversations.', '<span class="pill">LIVE ENGINE</span>')+`<div class="chat-shell card"><div class="chat-header"><div><div class="section-kicker">CUSTOMER SIMULATOR</div><h3>Customer conversation</h3><p class="ai-muted">Continue naturally — Intelispark keeps the conversation history.</p></div><button class="ghost" id="aiNewConversation" type="button">New test thread</button></div><div id="conversationMessages" class="conversation-messages"><div class="chat-loading">Loading conversation…</div></div><form id="conversationForm" class="chat-composer"><textarea id="conversationInput" rows="1" required placeholder="Message Intelispark as a customer…"></textarea><button class="primary" id="conversationSend" type="submit">Send</button></form><div class="chat-footer"><span>Independent intelligence · No external AI API</span><span>Saved automatically to Conversations</span></div></div>`;
    $('#conversationForm')?.addEventListener('submit',sendMessage);
    $('#conversationInput')?.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('#conversationForm')?.requestSubmit();}});
    $('#aiNewConversation')?.addEventListener('click',()=>{
      activeConversationId=null;activeMessages=[];
      const area=$('#conversationMessages');if(area)area.innerHTML='<div class="empty chat-empty">Start a new test thread by sending a message below. The current backend test customer will continue using its existing open WhatsApp thread.</div>';
      $('#conversationInput')?.focus();
    });
    (async()=>{
      try{
        await loadData();
        const candidate=APP.conversations[0];
        if(candidate){activeConversationId=candidate.id;activeMessages=await getMessages(candidate.id);}
        const area=$('#conversationMessages');
        if(area)area.innerHTML=activeMessages.length?activeMessages.map(messageBubble).join(''):'<div class="empty chat-empty">Start the customer conversation below.</div>';
        area?.scrollTo({top:area.scrollHeight});
      }catch(error){const area=$('#conversationMessages');if(area)area.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load the conversation.')}</div>`;}
    })();
  };

  window.renderConversations=async function(p){
    p.innerHTML=head('Conversations','Every customer message and Intelispark response is stored here as the live sales history.',`<button class="ghost" onclick="switchTab('ai')">Open customer simulator →</button>`)+`<div class="conversation-layout"><aside class="card conversation-sidebar"><div class="section-kicker">CUSTOMER THREADS</div><div id="conversationList" class="conversation-list">Loading…</div></aside><section class="card conversation-detail"><div class="conversation-detail-head"><div><div class="section-kicker">LIVE THREAD</div><h3>Conversation history</h3></div><span class="pill">SUPABASE SYNC</span></div><div id="conversationMessages" class="conversation-messages"><div class="empty">Select a customer conversation.</div></div></section></div>`;
    try{
      await loadData();
      const list=$('#conversationList');if(list)list.innerHTML=conversationList();
      document.querySelectorAll('.conversation-item').forEach(item=>item.addEventListener('click',()=>selectConversation(item.dataset.conversationId)));
      const candidate=activeConversationId||APP.conversations[0]?.id;
      if(candidate)await selectConversation(candidate);
    }catch(error){const list=$('#conversationList');if(list)list.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load conversations.')}</div>`;}
  };
})();
