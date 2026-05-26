export async function onRequestGet(context) {
  const client_id = context.env.DECAP_CMS_OAUTH_CLIENT_ID;

  if (!client_id) {
    return new Response('Server Error: DECAP_CMS_OAUTH_CLIENT_ID is not configured.', {
      status: 500,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }

  const scope = 'repo,user';
  const redirectUrl = `https://github.com/login/oauth/authorize?client_id=${client_id}&scope=${scope}`;
  return Response.redirect(redirectUrl, 302);
}
