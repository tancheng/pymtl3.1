class Connectable(object):

  def __new__( cls, *args ):
    inst = object.__new__( cls )

    # Use disjoint set to resolve connections
    inst._root      = inst
    inst._connected = [ inst ]

    return inst

  def _find_root( s ): # Disjoint set path compression
    if s._root == s:  return s
    s._root = s._root._find_root()
    return s._root

  def connect( s, writer ):
    assert isinstance( writer, Connectable ), "Unconnectable object!"

    x = s._find_root()
    y = writer._find_root()
    assert x != y, "Two nets are already unionized!"
    assert x == s, "One net signal cannot have two drivers! \n%s" % \
                   "Please check if the left side signal is at left side in another connection."

    # merge myself to the writer
    y._connected.extend( x._connected )
    x._connected = []
    x._root = y

  def __ior__( s, writer ):
    s.connect( writer )
    return s

class Wire(Connectable):

  def __init__( s, type_, default = None ):
    s.type_ = type_
    s.default = default

  def default_value( s ):
    return s.default if s.default != None else s.type_()

  def full_name( s ):
    name, idx = s._name_idx
    return ".".join( [ name[i] + "".join(["[%s]" % x for x in idx[i]]) \
                        for i in xrange(len(name)) ] )

class ValuePort(Wire):
  pass

class MethodPort(Connectable):

  def __init__( self, *args ):
    self._has_method = False
    assert len(args) <= 1
    if args:
      other = args[0]
      assert isinstance( other, MethodPort ), "Cannot connect to %s, which is not a MethodPort."
      self.connect( other )

  def attach_method( self, func ):
    self._func = func
    self._name = func.__name__
    self._has_method = True

  def has_method( self ):
    return self._has_method

  # Override
  def connect( self, other ):
    if self.has_method():
      super( MethodPort, other ).connect( self )
    else:
      super( MethodPort, self ).connect( other )

  # def __call__( self, *args, **kwargs ):
    # assert self._has_method, "what the hell are you doing here?" 
    # self._func( *args, **kwargs )
