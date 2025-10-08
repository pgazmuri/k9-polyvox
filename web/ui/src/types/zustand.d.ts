declare module "zustand" {
  export type SetState<T> = (partial: Partial<T> | ((state: T) => Partial<T>), replace?: boolean) => void;
  export type GetState<T> = () => T;

  export type StateCreator<T, Mps extends any[] = [], Mcs extends any[] = [], U = T> = (
    set: SetState<U>,
    get: GetState<U>,
    api: any
  ) => T;

  export function create<T>(initializer: StateCreator<T, [], [], T>): ((selector?: (state: T) => unknown) => any) & {
    getState: GetState<T>;
    setState: SetState<T>;
    subscribe: (listener: (state: T, prevState: T) => void) => () => void;
  };
}
