<script setup>
// 通知：只是知会，需要动手的事都在「要我处理」里。行为沿用原首页：按类别、只看未读、点一条标记已读并跳到来源单据。
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { createResource } from 'frappe-ui';
import { noteTarget } from '../../lib/navContext';

const router = useRouter();
const noteCategory = ref('mine');
const noteUnreadOnly = ref(true);
const notifications = createResource({
  url: 'rayher_hr_payroll.api.overview_entry.get_my_notification_feed', method: 'GET',
  makeParams: () => ({ category: noteCategory.value, unread_only: noteUnreadOnly.value ? 1 : 0, limit: 20 }), auto: true,
});
const noteReader = createResource({ url: 'rayher_hr_payroll.api.overview_entry.mark_notifications_read', method: 'POST' });
const noteCategories = computed(() => notifications.data?.categories || []);
const noteItems = computed(() => notifications.data?.items || []);

// 从首页点出去的链接都带 from=/dashboard，目标页的"返回"回到这里。
function openNote(item) {
  markNoteRead(item);
  const target = noteTarget(item);
  if (target) router.push(target);
}
function markNoteRead(item) {
  if (!item.unread) return;
  noteReader.submit({ names: JSON.stringify(item.names) }).then(() => notifications.reload());
}
function markCategoryRead() {
  noteReader.submit({ category: noteCategory.value }).then(() => notifications.reload());
}
watch([noteCategory, noteUnreadOnly], () => notifications.reload());
</script>

<template>
  <section class="db-card db-notes" aria-labelledby="db-notes-h">
    <div class="db-hd">
      <h2 id="db-notes-h">通知</h2>
      <span class="db-mut">只是知会你，需要你动手的事都在上面的「要我处理」里</span>
      <span class="db-notes-tools">
        <label class="db-check"><input v-model="noteUnreadOnly" type="checkbox" />只看未读</label>
        <button type="button" class="db-link" @click="markCategoryRead">本类全部已读</button>
      </span>
    </div>
    <div class="db-chips">
      <button v-for="item in noteCategories" :key="item.key" type="button" class="db-chip" :class="{ on: noteCategory === item.key }"
        :aria-pressed="noteCategory === item.key" @click="noteCategory = item.key">
        {{ item.label }}<b v-if="item.unread">{{ item.unread }}</b>
      </button>
    </div>
    <ul v-if="noteItems.length" class="db-rows">
      <li v-for="item in noteItems" :key="item.names[0]">
        <button type="button" class="db-row is-link db-note" :class="{ unread: item.unread }" @click="openNote(item)">
          <i class="db-dot" aria-hidden="true"></i>
          <span class="db-row-main">
            <span class="db-row-t">{{ item.event }}<template v-if="item.title">：{{ item.title }}</template></span>
            <span class="db-mut">{{ item.detail }}<template v-if="item.more"> · 该单据还有 {{ item.more }} 条</template></span>
          </span>
          <span class="db-mut db-note-time">{{ (item.created || '').slice(5, 16) }}</span>
        </button>
      </li>
    </ul>
    <p v-else-if="!notifications.loading" class="db-empty">这一类没有{{ noteUnreadOnly ? '未读' : '' }}通知</p>
  </section>
</template>
