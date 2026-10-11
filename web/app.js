import {$, esc, api, localIdentity, writeStorage, showError, notify} from './shared.js';
import {employerPage, adminPage} from './employer.js';

export async function boot() {
  const path=location.pathname;
  const active = path==='/employer'?(new URLSearchParams(location.search).get('view')==='company'?'company':'employer'):path==='/admin'?'admin':path==='/sources'?'sources':'discover';
  document.querySelectorAll('[data-nav]').forEach(link=>{link.classList.toggle('active',link.dataset.nav===active);if(link.dataset.nav===active)link.setAttribute('aria-current','page');});
  const identity=localIdentity();
  const identityForm=$('#identity-form');
  if(identityForm){identityForm.elements.user_id.value=identity.id;identityForm.elements.email.value=identity.email;identityForm.onsubmit=e=>{e.preventDefault();writeStorage('signal.localIdentity',{id:identityForm.elements.user_id.value.trim(),email:identityForm.elements.email.value.trim()});location.reload();};}
  try {
    const health=await api('/api/v1/health');
    if(health.runtime!=='local' && ['/employer','/admin','/sources'].includes(path))throw Error('This workspace needs the local Signal development server. Production sign-in is not connected yet.');
    if(path==='/employer') await employerPage();
    else if(path==='/admin')await adminPage();
    else if(path==='/sources'){const {sourcesPage}=await import('./sources.js');await sourcesPage();}
    else {const {candidatePage}=await import('./candidate.js');await candidatePage();}
  }catch(error){showError(error);$('#page').innerHTML='<div class="empty"><h1>We couldn’t load this page.</h1><p>Your data is still saved. Check that the local server is running, then try again.</p><button class="button primary" id="retry">Try again</button></div>';$('#retry').onclick=()=>location.reload();}
}
boot();
