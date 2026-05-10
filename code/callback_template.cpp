extern "C" {

#define ALWAYS_INLINE

void sink(void*);
[[gnu::const]] void* get();

struct Data {
    [[gnu::pure]] Data* next();
};

struct State {
    State()
    {
        enabled[0] = true;
        enabled[1] = true;
    }

    bool enabled[2];
};

using Cb = void (*)(State*, Data*);

ALWAYS_INLINE static void callback_tpl(Data* data, Cb cb1, Cb cb2, Cb cb3)
{
    State state;
    while (auto* i = data->next()) {
        cb1(&state, i);
        while (auto* j = i->next()) {
            cb2(&state, j);
            while (auto* k = j->next()) {
                cb3(&state, k);
            }
        }
    }
}

ALWAYS_INLINE static void noop(State*, Data*) {}

ALWAYS_INLINE static bool work1(State* state, Data*)
{
    sink(get());
    return true;
}

ALWAYS_INLINE static bool work2(State* state, Data* data)
{
    if (data)
        sink(get());
    return true;
}

ALWAYS_INLINE static void cb1(State* state, Data* data)
{
    if (state->enabled[0])
        state->enabled[0] = work1(state, data);
    if (state->enabled[1])
        state->enabled[1] = work2(state, data);
}

void noop_callback(Data* data)
{
    callback_tpl(data, cb1, noop, noop);
}
}
