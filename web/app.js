import {$, api, localIdentity, writeStorage, showError, capabilities} from './shared.js';

export async function boot() {
  const path=location.pathname;
  const active = path==='/employer'?(new URLSearchParams(location.search).get('view')==='company'?'company':'employer'):path==='/admin'?'admin':path==='/sources'?'sources':'discover';
  document.querySelectorAll('[data-nav]').forEach(link=>{link.classList.toggle('active',link.dataset.nav===active);if(link.dataset.nav===active)link.setAttribute('aria-current','page');});
  const identity=localIdentity();
  const identityForm=$('#identity-form');
  if(identityForm){identityForm.elements.user_id.value=identity.id;identityForm.elements.email.value=identity.email;identityForm.onsubmit=e=>{e.preventDefault();writeStorage('signal.localIdentity',{id:identityForm.elements.user_id.value.trim(),email:identityForm.elements.email.value.trim()});location.reload();};}
  try {
    const health=await api('/api/v1/health');
    capabilities.employer_posting=health.runtime==='local' || health.capabilities?.employer_posting===true;
    if(health.runtime!=='local' && ['/employer','/admin','/sources'].includes(path))throw Error('This workspace needs the local Signal development server. Production sign-in is not connected yet.');
    if(path==='/employer'){const {employerPage}=await import('./employer.js');await employerPage();}
    else if(path==='/admin'){const {adminPage}=await import('./employer.js');await adminPage();}
    else if(path==='/sources'){const {sourcesPage}=await import('./sources.js');await sourcesPage();}
    else {const {candidatePage}=await import('./candidate.js');await candidatePage();}
  }catch(error){showError(error);$('#page').innerHTML='<div class="empty"><h1>We couldn’t load this page.</h1><p>Please try again in a moment. Your saved jobs are still on this device.</p><button class="button primary" id="retry">Try again</button></div>';$('#retry').onclick=()=>location.reload();}
}
boot();
