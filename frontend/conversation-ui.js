/* Intelispark AI — persistent customer conversation interface. */
(function(){
  const BACKEND='/api';
  const REQUEST_TIMEOUT_MS=30000;
  let activeConversationId=null;
  let activeMessages=[];
  let sending=false;

  function formatTime(value){
    if(!value)return '';
    try{return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}catch(_){return '';}
  }

  function wait(ms){return new Promise(resolve=>setTimeout(resolve,ms));}

  async function getMessages(conversationId){
    if(!APP?.supabase||!conversationId)return [];
    const result=await APP.supabase.from('messages').select('id,sender_type,message_text,channel,created_at').eq('conversation_id',conversationId).order('created_at',{ascending:true});
    if(result.error)throw result.error;
    return result.data||[];
  }

  function messageBubble(message){
    const customer=message.sender_type==='customer';
    return `<div class="chat-row ${customer?'customer':'assistant'}"><div class="chat-avatar">${customer?'You':'I'}</div><div class="chat-bubble"><div class="chat-text">${esc(message.message_text||'')}</div><span class="chat-time">${formatTime(message.created_at)}</span></div></div>`;
  }

  function loadingBubble(){
    return `<div class="chat-row assistant" id="intelisparkThinking"><div class="chat-avatar">I</div><div class="chat-bubble"><div class="chat-text chat-thinking"><span>Thinking</span><span class="thinking-dots" aria-label="Intelispark is thinking"><i></i><i></i><i></i></span></div><span class="chat-time">Now</span></div></div>`;
  }

  function setComposerBusy(busy){
    sending=busy;
    const input=$('#conversationInput'),button=$('#conversationSend');
    if(input)input.disabled=busy;
    if(button){button.disabled=busy;button.textContent=busy?'Thinking…':'Send';button.setAttribute('aria-busy',busy?'true':'false');}
  }

  function removeThinking(){document.querySelector('#intelisparkThinking')?.remove();}

  async function deleteConversation(id){
    if(!APP?.supabase||!APP?.business?.id||!id)return;
    const conversation=APP.conversations.find(c=>c.id===id);
    const label=conversation?.channel||'customer';
    if(!confirm(`Delete this ${label} conversation?\n\nThis permanently removes the conversation and its stored messages from this shop. This cannot be undone.`))return;
    const deleteButton=document.querySelector(`[data-conversation-delete="${CSS.escape(id)}"]`);
    if(deleteButton){deleteButton.textContent='Deleting…';deleteButton.style.pointerEvents='none';}
    try{
      const session=await APP.supabase.auth.getSession();
      if(!session.data?.session)throw new Error('Your session has expired. Please sign in again.');
      const result=await APP.supabase.from('conversations').delete().eq('id',id).eq('business_id',APP.business.id).select('id').maybeSingle();
      if(result.error)throw result.error;
      activeConversationId=null;activeMessages=[];
      await loadData();renderTab();toast('Conversation deleted successfully.');
    }catch(error){
      console.error('[Intelispark conversation delete]',error);
      if(deleteButton){deleteButton.textContent='Delete';deleteButton.style.pointerEvents='';}
      toast(error?.message||'Could not delete the conversation.');
    }
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
    }catch(error){
      console.error('[Intelispark conversation load]',error);
      if(area)area.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load conversation.')}</div>`;
    }
  }

  function conversationList(){
    if(!APP?.conversations?.length)return '<div class="empty">No customer conversations yet.</div>';
    return APP.conversations.map((conversation)=>{
      const id=String(conversation.id||'');
      const title=conversation.title||conversation.customer_name||'Customer conversation';
      const channel=conversation.channel||'whatsapp';
      const created=String(conversation.created_at||'').slice(0,16).replace('T',' ');
      return '<div class="conversation-item '+(id===activeConversationId?'active':'')+'" data-conversation-id="'+esc(id)+'" role="button" tabindex="0">'+
        '<div class="conversation-item-main"><b>'+esc(title)+'</b><p>'+esc(channel)+' • '+esc(created)+'</p></div>'+
        '<button class="text-btn conversation-delete" type="button" data-conversation-delete="'+esc(id)+'" aria-label="Delete conversation">Delete</button></div>';
    }).join('');
  }
  async function refreshConversationList(){
    await loadData();
    const list=$('#conversationList');
    if(list)list.innerHTML=conversationList();
    bindConversationList();
    if(activeConversationId)await selectConversation(activeConversationId);
  }

  function bindConversationList(){
    document.querySelectorAll('.conversation-item').forEach(item=>item.addEventListener('click',event=>{
      if(event.target.closest('[data-conversation-delete]'))return;
      selectConversation(item.dataset.conversationId);
    }));
  }

  async function fetchReply(message,token){
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),REQUEST_TIMEOUT_MS);
    try{
      const response=await fetch(`${BACKEND}/sales/reply`,{
        method:'POST',
        headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`},
        body:JSON.stringify({business_id:APP.business.id,customer_message:message}),
        signal:controller.signal
      });
      const payload=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(payload.detail||`Intelligence request failed (${response.status}).`);
      const reply=payload.reply||payload.response||payload.message;
      if(!reply)throw new Error('Intelispark returned an empty response.');
      return {reply,conversationId:payload.conversation_id};
    }catch(error){
      if(error?.name==='AbortError')throw new Error('Intelispark took too long to respond. Please try again.');
      throw error;
    }finally{clearTimeout(timeout);}
  }

  async function sendMessage(event){
    event.preventDefault();
    if(sending)return;
    const input=$('#conversationInput'),message=input?.value.trim();
    if(!message||!APP.business||!APP.user)return;
    setComposerBusy(true);
    const area=$('#conversationMessages');
    const temporary={id:`temp-${Date.now()}`,sender_type:'customer',message_text:message,created_at:new Date().toISOString()};
    if(area){
      area.insertAdjacentHTML('beforeend',messageBubble(temporary)+loadingBubble());
      area.scrollTo({top:area.scrollHeight,behavior:'smooth'});
    }
    input.value='';
    try{
      const session=await APP.supabase.auth.getSession(),token=session.data?.session?.access_token;
      if(!token)throw new Error('Your session has expired. Please sign in again.');
      const result=await fetchReply(message,token);
      activeConversationId=result.conversationId||activeConversationId;
      if(!activeConversationId)throw new Error('The response was received, but no conversation ID was returned.');
      // Prefer the persisted Supabase history so the UI always shows exactly what was saved.
      activeMessages=await getMessages(activeConversationId);
      removeThinking();
      if(area)area.innerHTML=activeMessages.length?activeMessages.map(messageBubble).join(''):'<div class="empty">Response received, but no saved messages were found.</div>';
      area?.scrollTo({top:area.scrollHeight,behavior:'smooth'});
      await refreshConversationList();
    }catch(error){
      console.error('[Intelispark customer simulator]',error);
      removeThinking();
      if(area){
        area.insertAdjacentHTML('beforeend',`<div class="ai-error"><b>Could not complete that message.</b><br>${esc(error.message||'Please try again.')}</div>`);
        area.scrollTo({top:area.scrollHeight,behavior:'smooth'});
      }
      // Restore the unsent text so a temporary backend/network failure never loses the customer's message.
      if(input&&!input.value)input.value=message;
    }finally{
      setComposerBusy(false);
      input?.focus();
    }
  }

  window.renderAI=function(p){
    p.innerHTML=head('Test Intelispark','Talk to the intelligence engine as a customer. Every message is grounded in this shop’s Supabase catalog and saved to Conversations.', '<span class="pill">LIVE ENGINE</span>')+`<div class="chat-shell card"><div class="chat-header"><div><div class="section-kicker">CUSTOMER SIMULATOR</div><h3>Customer conversation</h3><p class="ai-muted">Continue naturally — Intelispark keeps the conversation history.</p></div><button class="ghost" id="aiNewConversation" type="button">New test thread</button></div><div id="conversationMessages" class="conversation-messages"><div class="chat-loading">Loading conversation…</div></div><form id="conversationForm" class="chat-composer"><textarea id="conversationInput" rows="1" required placeholder="Message Intelispark as a customer…"></textarea><button class="primary" id="conversationSend" type="submit">Send</button></form><div class="chat-footer"><span>Grounded in your catalog and business profile</span><span>Saved automatically to Conversations</span></div></div>`;
    $('#conversationForm')?.addEventListener('submit',sendMessage);
    $('#conversationInput')?.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('#conversationForm')?.requestSubmit();}});
    $('#aiNewConversation')?.addEventListener('click',()=>{
      if(sending)return;
      activeConversationId=null;activeMessages=[];
      const area=$('#conversationMessages');
      if(area)area.innerHTML='<div class="empty chat-empty">Start a new test thread by sending a message below. The current backend test customer will continue using its existing open WhatsApp thread.</div>';
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
      }catch(error){
        console.error('[Intelispark conversation startup]',error);
        const area=$('#conversationMessages');if(area)area.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load the conversation.')}</div>`;
      }
    })();
  };

  window.renderConversations=async function(p){
    p.innerHTML=head('Conversations','Every customer message and Intelispark response is stored here as the live sales history.',`<button class="ghost" onclick="switchTab('ai')">Open customer simulator →</button>`)+`<div class="conversation-layout"><aside class="card conversation-sidebar"><div class="section-kicker">CUSTOMER THREADS</div><div id="conversationList" class="conversation-list">Loading…</div></aside><section class="card conversation-detail"><div class="conversation-detail-head"><div><div class="section-kicker">LIVE THREAD</div><h3>Conversation history</h3></div><span class="pill">SUPABASE SYNC</span></div><div id="conversationMessages" class="conversation-messages"><div class="empty">Select a customer conversation.</div></div></section></div>`;
    try{
      await loadData();
      const list=$('#conversationList');if(list)list.innerHTML=conversationList();
      bindConversationList();
      const listArea=$('#conversationList');
      listArea?.addEventListener('click',event=>{
        const deleteTarget=event.target.closest('[data-conversation-delete]');
        if(deleteTarget){event.preventDefault();event.stopPropagation();deleteConversation(deleteTarget.dataset.conversationDelete);}
      });
      listArea?.addEventListener('keydown',event=>{
        const deleteTarget=event.target.closest('[data-conversation-delete]');
        if(deleteTarget&&(event.key==='Enter'||event.key===' ')){event.preventDefault();deleteConversation(deleteTarget.dataset.conversationDelete);}
      });
      const candidate=activeConversationId||APP.conversations[0]?.id;
      if(candidate)await selectConversation(candidate);
    }catch(error){
      console.error('[Intelispark conversations startup]',error);
      const list=$('#conversationList');if(list)list.innerHTML=`<div class="ai-error">${esc(error.message||'Could not load conversations.')}</div>`;
    }
  };
})();