import { defineCollection, z } from 'astro:content';

const wiki = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    tags: z.array(z.string()).default([]),
    sources: z.array(z.string()).default([]),
    last_updated: z.string().optional(),
  }),
});

export const collections = {
  wiki,
};
