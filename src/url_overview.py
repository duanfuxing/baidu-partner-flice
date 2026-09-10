"""通过页面搜索 URL，并根据表格刷新判断查询完成。"""

import logging

from .errors import PageFlowError

LOGGER = logging.getLogger(__name__)

_READY = """root => {
    const visible = e => !!e.getClientRects().length;
    if ([...root.querySelectorAll('.el-skeleton, .el-skeleton__item, .el-loading-mask')]
        .some(visible)) return false;
    return [...root.querySelectorAll('tbody tr a[href], .el-table__empty-block')].some(visible);
}"""


def _query_and_wait(page, region, button, timeout):
    """监听表格 DOM 变化，不监听网络请求或访问框架内部状态。"""
    region.evaluate("""root => {
        const state = {changed: false, updated: performance.now()};
        const relevant = node => node.nodeType === 1 &&
            (node.matches('table, tbody, tr, .el-skeleton, .el-table__empty-block') ||
             node.querySelector('table, tbody, tr, .el-skeleton, .el-table__empty-block'));
        state.observer = new MutationObserver(records => {
            if (records.some(r =>
                (r.type === 'childList' && (r.target.closest('table, .el-table__empty-block') ||
                    [...r.addedNodes, ...r.removedNodes].some(relevant))) ||
                (r.type === 'characterData' && r.target.parentElement?.closest('table, .el-table__empty-block')) ||
                (r.type === 'attributes' && r.target.matches('.el-skeleton, .el-loading-mask')))) {
                state.changed = true;
                state.updated = performance.now();
            }
        });
        state.observer.observe(root, {subtree: true, childList: true, characterData: true,
                                     attributes: true, attributeFilter: ['hidden', 'style', 'class']});
        root.__urlSearchObservation = state;
    }""")
    try:
        button.click(timeout=timeout)
        page.wait_for_function("""root => {
            const visible = e => !!e.getClientRects().length;
            const error = [...document.querySelectorAll('.el-message--error, .el-notification--error')]
                .some(visible);
            if (error) return true;
            const state = root.__urlSearchObservation;
            if (!state?.changed || performance.now() - state.updated < 200) return false;
            if ([...root.querySelectorAll('.el-skeleton, .el-skeleton__item, .el-loading-mask')]
                .some(visible)) return false;
            return [...root.querySelectorAll('tbody tr a[href], .el-table__empty-block')].some(visible);
        }""", arg=region.element_handle(), timeout=timeout)
        errors = page.locator('.el-message--error, .el-notification--error')
        if any(errors.nth(i).is_visible() for i in range(errors.count())):
            raise PageFlowError('页面提示URL查询失败，停止，不使用旧结果')
    except PageFlowError:
        raise
    except Exception:
        raise PageFlowError('等待URL查询表格刷新超时，停止，不使用旧结果') from None
    finally:
        region.evaluate("""root => {
            root.__urlSearchObservation?.observer.disconnect();
            delete root.__urlSearchObservation;
        }""")


def search_url_overview(page, target_url: str, timeout: int) -> bool:
    regions = page.locator('.url-overview').filter(has_text='URL状态概览')
    regions = [regions.nth(i) for i in range(regions.count()) if regions.nth(i).is_visible()]
    if not regions:
        return False  # 旧页面保留原分页兼容。
    if len(regions) != 1:
        raise PageFlowError('URL搜索区域不唯一，停止匹配')
    region = regions[0]
    search = region.get_by_placeholder('请输入要查询的url链接', exact=True)
    query = region.get_by_role('button', name='查询', exact=True)
    if search.count() != 1 or query.count() != 1:
        raise PageFlowError('URL搜索控件不完整或不唯一，停止匹配')
    try:
        page.wait_for_function(_READY, arg=region.element_handle(), timeout=timeout)
    except Exception:
        raise PageFlowError('等待URL列表初始数据加载超时，尚未执行搜索') from None

    # 正常页面直接查询；仅已有其他筛选时才重置，避免多发一次页面查询。
    url_id = region.get_by_placeholder('请输入要查询的urlid', exact=True)
    status = region.locator('.el-form-item').filter(has_text='审核状态').locator(
        '.el-select__selected-item:not(.is-transparent):not(.el-select__placeholder)')
    has_status = any(text.strip() and '请选择' not in text for text in status.all_inner_texts())
    if (url_id.count() and url_id.input_value().strip()) or has_status:
        reset = region.get_by_role('button', name='重置', exact=True)
        if reset.count() != 1:
            raise PageFlowError('URL列表有其他筛选但无法重置，停止匹配')
        _query_and_wait(page, region, reset, timeout)
    LOGGER.info('URL列表：输入目标链接并点击查询')
    search.fill(target_url, timeout=timeout)
    _query_and_wait(page, region, query, timeout)
    next_page = region.locator('.el-pagination .btn-next')
    if any(next_page.nth(i).is_visible() and next_page.nth(i).is_enabled()
           and 'disabled' not in (next_page.nth(i).get_attribute('class') or '')
           for i in range(next_page.count())):
        raise PageFlowError('URL搜索结果超过一页，无法确认目标唯一，请检查输入链接')
    LOGGER.info('URL列表：搜索表格已刷新，开始精确匹配')
    return True
