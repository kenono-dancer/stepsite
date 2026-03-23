import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const blog = defineCollection({
  loader: glob({ base: "./src/content/blog", pattern: "**/*.{md,mdx}" }),
  schema: z.object({
    title:       z.string(),
    pubDate:     z.coerce.date(),
    description: z.string().optional().default(""),
    author:      z.string().optional().default(""),
    tags:        z.array(z.string()).optional().default([]),
    updatedDate: z.coerce.date().optional(),
    image: z
      .object({
        url: z.string(),
        alt: z.string().optional().default(""),
      })
      .optional(),
  }),
});

export const collections = { blog };
