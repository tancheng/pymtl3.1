#=========================================================================
# ComponentLevel3.py
#=========================================================================

from NamedObject import NamedObject
from ComponentLevel2 import ComponentLevel2
from Connectable import Connectable, Signal, InVPort, OutVPort, Wire, Const
from errors      import InvalidConnectionError, SignalTypeError, NoWriterError, MultiWriterError
from collections import defaultdict, deque

import inspect, ast # for error message

class ComponentLevel3( ComponentLevel2 ):

  #-----------------------------------------------------------------------
  # Private methods
  #-----------------------------------------------------------------------

  def __new__( cls, *args, **kwargs ):
    inst = super( ComponentLevel3, cls ).__new__( cls, *args, **kwargs )
    inst._call_kwargs = None
    inst._adjacency   = defaultdict(set)
    # inst._consts      = set()
    return inst

  # Override
  def _declare_vars( s ):
    super( ComponentLevel3, s )._declare_vars()

    s._all_adjacency = defaultdict(set)

  # Override
  def _collect_vars( s, m ):
    super( ComponentLevel3, s )._collect_vars( m )

    if isinstance( m, ComponentLevel3 ):
      for k in m._adjacency:
        s._all_adjacency[k] |= m._adjacency[k]

  # Override
  def _construct( s ):
    """ We override _construct here to finish the saved __call__
    connections right after constructing the model. The reason why we
    take this detour instead of connecting in __call__ directly, is that
    __call__ is done before setattr, and hence the child components don't
    know their name yet. _constructed is called in setattr after name
    tagging, so this is valid. (see NamedObject.py). """

    if not s._constructed:

      if not s._kwargs: s.construct( *s._args )
      else:             s.construct( *s._args, **s._kwargs )

      if s._call_kwargs is not None: # s.a = A()( b = s.b )
        s._continue_call_connect()

      s._constructed = True

  @staticmethod
  def _connect_objects( o1, o2, adjacency_dict ):
    """ Connect two objects. If one of them is integer, create a new Const
    that wraps around it in 's'. This method refactors will be called by other
    public APIs. """

    if isinstance( o1, int ) or isinstance( o2, int ): # special case
      if isinstance( o1, int ):
        o1, o2 = o2, o1 # o1 is signal, o2 is int
      assert isinstance( o1, Signal )

      o2   = Const( o1.Type, o2 )
      host = o1.get_host_component()

      if isinstance( o1, InVPort ):
        # connecting constant to inport should be at the parent level
        host = host.get_parent_object()

      o2._parent_obj = host
      # host._consts.add( const )

    assert o1.Type == o2.Type, "Type mismatch {} != {}".format( o1.Type, o2.Type )
    o1._connect( o2, adjacency_dict )

  def _continue_call_connect( s ):
    """ Here we continue to establish the connections from signals of the
    parent object, to signals in the current object. Since it is the
    parent that connects a constant integer to a signal, we should point
    the Const object back to the parent object by setting _parent_obj to
    s._parent_obj."""

    try: # Catch AssertionError from _connect

      # Process saved __call__ kwargs
      for (kw, target) in s._call_kwargs.iteritems():

        try:
          obj = getattr( s, kw )
        except AttributeError:
          raise InvalidConnectionError( "{} is not a member of class {}".format(kw, s.__class__) )

        # Obj is a list of signals
        if   isinstance( obj, list ):
          # Make sure the connection target is a dictionary {idx: obj}
          if not isinstance( target, dict ):
            raise InvalidConnectionError( "We only support a dictionary when '{}' is an array.".format( kw ) )
          for idx, item in target.iteritems():
            s._connect_objects( obj[idx], item, s._adjacency )

        # Obj is a single signal
        # If the target is a list, it's fanout connection
        elif isinstance( target, tuple ) or isinstance( target, list ):
          for item in target:
            s._connect_objects( obj, item, s._adjacency )

        # Target is a single object
        else:
          s._connect_objects( obj, target, s._adjacency )

    except AssertionError as e:
      raise InvalidConnectionError( "Invalid connection for {}:\n{}".format( kw, e ) )

  @staticmethod
  def _floodfill_nets( signal_list, adjacency ):
    """ Floodfill to find out connected nets. Return a list of sets. """

    nets = []
    visited = set()
    pred    = {} # detect cycle that has >=3 nodes
    for obj in signal_list:
      if obj in adjacency and obj not in visited:
        net = set()
        Q   = deque( [ obj ] )
        while Q:
          u = Q.popleft()
          visited.add( u )
          net.add( u )
          for v in adjacency[u]:
            if v not in visited:
              pred[v] = u
              Q.append( v )
            elif v is not pred[u]:
              raise InvalidConnectionError(repr(v)+" is in a connection loop.")
        nets.append( net )
    return nets

  def _resolve_var_connections( s, signal_list ):
    """ The case of nested data struct: the writer of a net can be one of
    the three: signal itself (s.x.a), ancestor (s.x), descendant (s.x.b)

    An iterative algorithm is required to mark the writers. The example
    is the following. Net 1's writer is s.x and one reader is s.y.
    Net 2's writer is s.y.a (known ONLY after Net 1's writer is clear),
    one reader is s.z. Net 3's writer is s.z.a (known ...), and so forth

    Note that s.x becomes writer when WR s.x.a or WR s.x.b, but s.x then
    cannot propagate back to s.x.b or s.x.a.

    The original state is all the writers from all update blocks.
    writer_prop is a dict {x:y} that stores potential writers and
    whether the writer can propagate to other nets. After a net is
    resolved from headless condition, its readers become writers.

    The case of slicing: slices of the same wire are only one level
    deeper, so all of those parent/child relationship work easily.
    However, unlike different fields of a data struct, different slices
    may _intersect_, so they need to check sibling slices' write/read
    status as well. """

    # First of all, bfs the "forest" to find out all nets

    nets = s._floodfill_nets( s._all_signals, s._all_adjacency )

    # Then figure out writers: all writes in upblks and their nest objects

    writer_prop = {}

    for blk, writes in s._all_upblk_writes.iteritems():
      for obj in writes:
        writer_prop[ obj ] = True # propagatable

        obj = obj._parent_obj
        while obj.is_signal():
          writer_prop[ obj ] = False
          obj = obj._parent_obj

    # Find the host object of every net signal
    # and then leverage the information to find out top level input port

    for net in nets:
      for member in net:
        host = member
        while not isinstance( host, ComponentLevel3 ):
          host = host._parent_obj # go to the component
        member._host = host

        if isinstance( member, InVPort ) and member._host == s:
          writer_prop[ member ] = True

    headless = nets
    headed   = []

    # Convention: we store a net in a tuple ( writer, set([readers]) )
    # The first element is writer; it should be None if there is no
    # writer. The second element is a set of signals including the writer.

    while headless:
      new_headless = []
      wcount = len(writer_prop)

      # For each net, figure out the writer among all vars and their
      # ancestors. Moreover, if x's ancestor has a writer in another net,
      # x should be the writer of this net.
      #
      # If there is a writer, propagate writer information to all readers
      # and readers' ancestors. The propagation is tricky: assume s.x.a
      # is in net, and s.x.b is written in upblk, s.x.b will mark s.x as
      # an unpropagatable writer because later s.x.a shouldn't be marked
      # as writer by s.x.
      #
      # Similarly, if x[0:10] is written in update block, x[5:15] can
      # be a unpropagatable writer because we don't want x[5:15] to
      # propagate to x[12:17] later.

      for net in headless:
        has_writer = False

        for v in net:
          obj = None
          try:
            # Check if itself is a writer or a constant
            if v in writer_prop or isinstance( v, Const ):
              assert not has_writer
              has_writer, writer = True, v

            # Check if an ancestor is a propagatable writer
            obj = v.get_parent_object()
            while obj.is_signal():
              if obj in writer_prop and writer_prop[ obj ]:
                assert not has_writer
                has_writer, writer = True, v
                break
              obj = obj.get_parent_object()

            # Check sibling slices
            for obj in v.get_sibling_slices():
              if obj.slice_overlap( v ):
                if obj in writer_prop and writer_prop[ obj ]:
                  assert not has_writer
                  has_writer, writer = True, v

          except AssertionError:
            raise MultiWriterError( \
            "Two-writer conflict \"{}\"{}, \"{}\" in the following net:\n - {}".format(
              repr(v), "" if not obj else "(as \"{}\" is written somewhere else)".format( repr(obj) ),
              repr(writer), "\n - ".join([repr(x) for x in net])) )

        if not has_writer:
          new_headless.append( net )
          continue

        # Child s.x.y of some propagatable s.x, or sibling of some
        # propagatable s[a:b].
        # This means that at least other variables are able to see s.x/s[a:b]
        # so it doesn't matter if s.x.y is not in writer_prop
        if writer not in writer_prop:
          pass

        for v in net:
          if v != writer:
            writer_prop[ v ] = True # The reader becomes new writer

            obj = v.get_parent_object()
            while obj.is_signal():
              if obj not in writer_prop:
                writer_prop[ obj ] = False
              obj = obj.get_parent_object()

        headed.append( (writer, net) )

      if wcount == len(writer_prop): # no more new writers
        break
      headless = new_headless

    return headed + [ (None, x) for x in headless ]

  def _check_port_in_nets( s ):
    nets = s._all_nets

    # The case of connection is very tricky because we put a single upblk
    # in the lowest common ancestor node and the "output port" chain is
    # inverted. So we need to deal with it here ...
    #
    # The gist is that the data flows from deeper level writer to upper
    # level readers via output port, to the same level via wire, and from
    # upper level to deeper level via input port

    headless = [ signals for writer, signals in nets if writer is None ] # remove None
    if headless:
      raise NoWriterError( headless )

    for writer, _ in nets:

      # We need to do DFS to check all connected port types
      # Each node is a writer when we expand it to other nodes

      S = deque( [ writer ] )
      visited = set( [ writer ] )

      while S:
        u = S.pop() # u is the writer
        whost = u._host

        for v in s._all_adjacency[u]: # v is the reader
          if v not in visited:
            visited.add( v )
            S.append( v )
            rhost = v._host

            # 1. have the same host: writer_host(x)/reader_host(x):
            # Hence, writer is anything, reader is wire or outport
            if   whost == rhost:
              valid = ( isinstance( u, Signal )  or isinstance( u, Const) ) and \
                      ( isinstance( v, OutVPort) or isinstance( v, Wire ) )
              if not valid:
                raise SignalTypeError( \
"""[Type 5] Invalid port type detected at the same host component "{}" (class {})

- {} "{}" cannot be driven by {} "{}".

  Note: InVPort x.y cannot be driven by x.z""" \
          .format(  repr(rhost), type(rhost).__name__,
                    type(v).__name__, repr(v), type(u).__name__, repr(u) ) )

            # 2. reader_host(x) is writer_host(x.y)'s parent:
            # Hence, writer is outport, reader is wire or outport
            # writer cannot be constant
            elif rhost == whost._parent_obj:
              valid = isinstance( u, OutVPort) and \
                    ( isinstance( v, OutVPort ) or isinstance( v, Wire ) )

              if not valid:
                raise SignalTypeError( \
"""[Type 6] Invalid port type detected when the driver lies deeper than drivee:

- {} "{}" of {} (class {}) cannot be driven by {} "{}" of {} (class {}).

  Note: InVPort x.y cannot be driven by x.z.a""" \
          .format(  type(v).__name__, repr(v), repr(rhost), type(rhost).__name__,
                    type(u).__name__, repr(u), repr(whost), type(whost).__name__ ) )

            # 3. writer_host(x) is reader_host(x.y)'s parent:
            # Hence, writer is inport or wire, reader is inport
            # writer can be constant
            elif whost == rhost._parent_obj:
              # valid = ( isinstance( u, InVPort ) or isinstance( u, Wire ) \
                                                 # or isinstance( u, Const)) and \
                        # isinstance( v, InVPort )

              # if not valid:
                # raise SignalTypeError( \
# """[Type 7] Invalid port type detected when the driver lies shallower than drivee:

# - {} "{}" of {} (class {}) cannot be driven by {} "{}" of {} (class {}).

  # Note: OutVPort/Wire x.y.z cannot be driven by x.a""" \
          # .format(  type(v).__name__, repr(v), repr(rhost), type(rhost).__name__,
                    # type(u).__name__, repr(u), repr(whost), type(whost).__name__ ) )

            # Shunning 9/12/2017: Actually in this case writer can be outport
              valid = ( isinstance( u, Signal ) or isinstance( u, Const )) and \
                        isinstance( v, InVPort )

              if not valid:
                raise SignalTypeError( \
"""[Type 7] Invalid port type detected when the driver lies shallower than drivee:

- {} "{}" of {} (class {}) cannot be driven by {} "{}" of {} (class {}).

  Note: OutVPort/Wire x.y.z cannot be driven by x.a""" \
          .format(  type(v).__name__, repr(v), repr(rhost), type(rhost).__name__,
                    type(u).__name__, repr(u), repr(whost), type(whost).__name__ ) )

            # 4. hosts have the same parent: writer_host(x.y)/reader_host(x.z)
            # This means that the connection is fulfilled in x
            # Hence, writer is outport and reader is inport
            # writer cannot be constant
            elif whost._parent_obj == rhost._parent_obj:
              valid = isinstance( u, OutVPort ) and isinstance( v, InVPort )

              if not valid:
                raise SignalTypeError( \
"""[Type 8] Invalid port type detected when the drivers is the sibling of drivee:

- {} "{}" of {} (class {}) cannot be driven by {} "{}" of {} (class {}).

  Note: Looks like the connection is fulfilled in "{}".
        OutVPort/Wire x.y.z cannot be driven by x.a.b""" \
          .format(  type(v).__name__, repr(v), repr(rhost), type(rhost).__name__,
                    type(u).__name__, repr(u), repr(whost), type(whost).__name__,
                    repr(whost._parent_obj) ) )
            # 5. neither host is the other's parent nor the same.
            else:
              raise SignalTypeError("""[Type 9] "{}" and "{}" cannot be connected:

- host objects "{}" and "{}" are too far in the hierarchy.""" \
              .format( repr(u), repr(v), repr(whost), repr(rhost) ) )

  #-----------------------------------------------------------------------
  # Construction-time APIs
  #-----------------------------------------------------------------------

  def __call__( s, *args, **kwargs ):
    """ This syntactic sugar supports the following one-liner:
      >>> s.x = SomeReg(Bits1)( in_ = s.in_ )
    It connects s.in_ to s.x.in_ in the same line as model construction.
    """
    assert args == ()
    if s._constructed:
      raise InvalidConnectionError("Connection using __call__, "
                                   "i.e. s.x( a = s.a ), is illegal "
                                   "after constructing s.x")
    s._call_kwargs = kwargs
    return s

  def connect( s, o1, o2 ):
    try:
      s._connect_objects( o1, o2, s._adjacency )
    except AssertionError as e:
      raise InvalidConnectionError( "\n{}".format(e) )

  def connect_pairs( s, *args ):
    if len(args) & 1 != 0:
       raise InvalidConnectionError( "Odd number ({}) of objects provided.".format( len(args) ) )

    for i in xrange(len(args)>>1) :
      try:
        s.connect( args[ i<<1 ], args[ (i<<1)+1 ] )
      except InvalidConnectionError as e:
        raise InvalidConnectionError( "\n- In connect_pair, when connecting {}-th argument to {}-th argument\n{}\n " \
              .format( (i<<1)+1, (i<<1)+2 , e ) )

  #-----------------------------------------------------------------------
  # elaborate
  #-----------------------------------------------------------------------

  # Override
  def elaborate( s ):
    if s._constructed:
      return

    NamedObject.elaborate( s )
    s._declare_vars()

    s._all_components = s._recursive_collect( lambda x: isinstance( x, ComponentLevel3 ) )
    for c in s._all_components:
      c._elaborate_top = s
      c._elaborate_read_write_func()
      s._collect_vars( c )

    s._all_signals = s._recursive_collect( lambda x: isinstance( x, Signal ) )
    s._all_nets    = s._resolve_var_connections( s._all_signals )

    s.check()

  #-----------------------------------------------------------------------
  # Public APIs (only can be called after elaboration)
  #-----------------------------------------------------------------------

  # Override
  def check( s ):
    s._check_upblk_writes()
    s._check_port_in_upblk()
    s._check_port_in_nets()

  # Override
  def get_all_components( s ):
    return s._recursive_collect( lambda x: isinstance( x, ComponentLevel3 ) )

  def get_all_nets( s ):
    try:
      return s._all_nets
    except AttributeError:
      raise NotElaboratedError()

  # Override
  def delete_component_by_name( s, name ):

    # This nested delete function is to create an extra layer to properly
    # call garbage collector

    def _delete_component_by_name( parent, name ):
      obj = getattr( parent, name )
      top = s._elaborate_top

      # Remove all components and uncollect metadata

      removed_components = obj.get_all_components()
      top._all_components -= removed_components

      for x in removed_components:
        assert x._elaborate_top is top
        top._uncollect_vars( x )

      for x in obj._recursive_collect():
        del x._parent_obj

      removed_signals = obj._recursive_collect( lambda x: isinstance( x, Signal ) )
      top._all_signals -= removed_signals

      # TODO somehow save the adjs for reconnection

      for x in removed_signals:
        for other in top._all_adjacency[x]:
          # If other will be removed, we don't need to remove it here ..
          # Check if this is a broken connection
          if   other not in removed_signals:
            top._all_adjacency[other].remove( x )

        del top._all_adjacency[x]
      # top._all_nets = top._resolve_var_connections( top._all_signals )

      new_nets = []
      for writer, signals in top._all_nets:
        broken_nets = s._floodfill_nets( signals, top._all_adjacency )
        
        if len(broken_nets) == 1: # the net is not broken
          new_nets.append( (writer, signals) )
          continue
        else:
          for net_signals in broken_nets:
            if len(net) == 1: continue

            if writer in net_signals:
              new_nets.append( (writer, signals) )
            else:
              new_nets.append( (None, signals) )

      top._all_nets = new_nets

      delattr( s, name )

    _delete_component_by_name( s, name )
    import gc
    gc.collect()

  # Override
  def add_component_by_name( s, name, obj ):
    assert not hasattr( s, name )
    NamedObject.__setattr__ = NamedObject.__setattr_for_elaborate__
    setattr( s, name, obj )
    del NamedObject.__setattr__

    top = s._elaborate_top

    added_components = obj.get_all_components()
    top._all_components |= added_components

    for c in added_components:
      c._elaborate_top = top
      c._elaborate_read_write_func()
      top._collect_vars( c )

    added_signals = obj._recursive_collect( lambda x: isinstance( x, Signal ) )
    top._all_signals |= added_signals

    top._all_nets += top._resolve_var_connections( added_signals )

  def add_connection( s, o1, o2 ):
    # TODO support string arguments and non-top s
    assert s._elaborate_top is s, "Adding connection by passing objects " \
                                  "is only allowed at top, but this API call " \
                                  "is on {}.".format( "top."+repr(s)[2:] )

    added_adjacency = defaultdict(set)
    try:
      s._connect_objects( o1, o2, added_adjacency )
    except AssertionError as e:
      raise InvalidConnectionError( "\n{}".format(e) )

    for x, adjs in added_adjacency.iteritems():
      s._all_adjacency[x].update( adjs )

    # This works, but might be too slow
    s._all_nets = s._resolve_var_connections( s._all_signals )
