import { defineStore } from 'pinia'

export type OperatorRole = 'admin' | 'member'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: 'admin' as OperatorRole,
    shiftLabel: '白班 08:00-20:00',
    scope: '数据洞察分析工作台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isAdmin: (state) => state.role === 'admin',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setIdentity(operator: string, role: OperatorRole) {
      this.operator = operator
      this.role = role
    },
  },
})
