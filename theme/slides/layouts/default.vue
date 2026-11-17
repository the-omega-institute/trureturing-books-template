<!--
  The frame shared by every slide: void background with aurora, scanlines and corner brackets,
  a header (book code // deck title, section on the right) and a footer (book · version, the followed
  trureturing branch (legacy: pinned commit), page number). Frontmatter:
    section: "…"   right side of the header
    bare: true     no header and footer (slides that draw their own frame, such as a cover)
  Header and footer read the deck headmatter: deck.code, deck.title, deck.book, deck.version.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useSlideContext } from '@slidev/client'
import { pinned } from '../lean'
import PageNo from '../components/PageNo.vue'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ section?: string, bare?: boolean, class?: string }>()
const { $slidev } = useSlideContext()
const deck = computed<Record<string, string>>(() => ($slidev.configs as any).deck ?? {})
</script>

<template>
  <div class="slide" :class="[props.class, { bare: props.bare }]">
    <div class="tr-fx" aria-hidden="true"><i class="bracket tl" /><i class="bracket tr" /><i class="bracket bl" /><i class="bracket br" /></div>
    <header v-if="!props.bare" class="hdr">
      <span class="hdr-l"><b>{{ deck.code }}</b><span class="hdr-sep">//</span><span>{{ deck.title }}</span></span>
      <span v-if="props.section" class="hdr-r">{{ props.section }}</span>
    </header>
    <slot />
    <footer v-if="!props.bare" class="ftr">
      <span class="ftr-l">{{ deck.book }}<span v-if="deck.book && deck.version" class="ftr-sep">·</span><span v-if="deck.version">v{{ deck.version }}</span></span>
      <span v-if="pinned.short" class="ftr-c">trureturing<span class="ftr-at">@</span>{{ pinned.short }}</span>
      <PageNo />
    </footer>
  </div>
</template>
