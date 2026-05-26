export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const code = url.searchParams.get('code');
  
  const client_id = context.env.DECAP_CMS_OAUTH_CLIENT_ID;
  const client_secret = context.env.DECAP_CMS_OAUTH_CLIENT_SECRET;

  if (!client_id || !client_secret) {
    return new Response('Server Error: OAuth environment variables are not configured.', {
      status: 500,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }

  // GitHubへアクセストークンをリクエスト
  const response = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id, client_secret, code }),
  });

  const data = await response.json();

  if (data.error) {
    return new Response(`OAuth Error: ${data.error}`, { status: 400 });
  }

  const token = data.access_token;
  const message = 'authorization:github:success:' + JSON.stringify({ token, provider: 'github' });

  // 親ウィンドウにトークンを送信してポップアップを閉じる
  const html = `<!DOCTYPE html>
<html>
<head><title>Authenticating...</title></head>
<body>
<script>
(function() {
  var message = ${JSON.stringify(message)};
  function receiveMessage(e) {
    window.opener.postMessage(message, e.origin);
    window.close();
  }
  window.addEventListener('message', receiveMessage, false);
  window.opener.postMessage('authorizing:github', '*');
})();
</script>
</body>
</html>`;

  return new Response(html, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}
