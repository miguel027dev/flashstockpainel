const CACHE='flashstock-erp-v4-1';
const CORE=[
  '/static/css/app.css',
  '/static/css/login.css',
  '/static/css/shared.css',
  '/static/css/home-original.css',
  '/static/js/app.js',
  '/static/js/shared.js',
  '/static/js/home.js',
  '/static/icon.svg'
];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==location.origin)return;
  if(url.pathname.startsWith('/media/produtos/')||url.pathname.startsWith('/static/')){
    event.respondWith(caches.open(CACHE).then(async cache=>{
      const hit=await cache.match(event.request);
      const network=fetch(event.request).then(resp=>{if(resp.ok)cache.put(event.request,resp.clone());return resp}).catch(()=>hit);
      return hit||network;
    }));
    return;
  }
  event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));
});
