import type { APIRoute } from 'astro';

export const GET: APIRoute = () => {
  const content = `User-agent: *
Disallow:
Sitemap: https://step.itxdancer.com/sitemap-index.xml
`;

  return new Response(content, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
