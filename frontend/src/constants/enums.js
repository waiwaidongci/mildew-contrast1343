export const ROLE = {admin:'复核主管', analyst:'分析员', viewer:'只读查看'};
export const STATUS = {queued:'排队中', running:'正在计算', complete:'计算完成', failed:'运行失败'};
export const REVIEW = {pending:'待复核', accepted:'已通过', returned:'已退回'};
export const MERGE = {awaiting:'等待库房', conflict:'存在冲突', ready:'已齐备待发布', published:'已发布'};
export const ATTEMPT = {accepted:'已入账', duplicate:'重试已确认', stale:'迟到未入账', replaced:'已换包', rejected:'已拒绝', returned:'已退回'};
